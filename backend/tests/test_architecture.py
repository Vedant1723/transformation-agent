"""Contract and layering checks; no external database or Java service required."""
import ast
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.api.transformation_handoff import get_current_user, get_db
from app.services import transformations

ROOT = Path(__file__).resolve().parents[1] / 'app'


def test_service_layer_has_no_controllers_or_dependency_injection():
    for path in (ROOT / 'services').glob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or '').startswith('app.api'), path
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in ('APIRouter', 'Depends'), path


@pytest.fixture
def client():
    api = app.state.integration_api
    api.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1)
    api.dependency_overrides[get_db] = lambda: object()
    with TestClient(app) as client:
        yield client
    api.dependency_overrides.clear()


def test_generate_controller_preserves_contract(client, monkeypatch):
    observed = []
    def generate(request, user, db):
        observed.append((request.source.payload, user.id))
        return {'success': True, 'data': {'template': 'example'}}
    monkeypatch.setattr(transformations, 'transformation_chat', generate)
    response = client.post('/transformation-agent/api/v2/transformations/generate', json={
        'direction': 'REQUEST', 'source': {'payload': {'amount': 25}},
        'target': {'payload': {'total': 0}}})
    assert response.status_code == 200
    assert response.json() == {'st': True, 'msg': 'success', 'msgId': 'SUCCESS', 'data': {'template': 'example'}}
    assert observed == [({'amount': 25}, 1)]


def test_failed_template_is_not_transport_failure(client, monkeypatch):
    monkeypatch.setattr(transformations, 'test_template', lambda *args: {'success': True, 'data': {'passed': False}})
    response = client.post('/transformation-agent/api/v2/transformations/test', json={'template': 'bad', 'input_payload': {}})
    assert response.status_code == 200
    assert response.json()['st'] is True
    assert response.json()['data']['passed'] is False


def test_validation_error_envelope(client):
    response = client.post('/transformation-agent/api/v2/transformations/generate', json={})
    assert response.status_code == 422
    assert set(response.json()) == {'st', 'msg', 'msgId', 'data'}
    assert response.json()['st'] is False


def test_untrusted_gateway_rejected(monkeypatch):
    monkeypatch.setenv('GATEWAY_SHARED_SECRET', 'synthetic-test-secret-' * 3)
    response = TestClient(app).get('/transformation-agent/api/v2/transformations/model')
    assert response.status_code == 401
    assert response.json()['msgId'] == 'UNAUTHORIZED'


def test_no_local_auth_in_openapi():
    schema = TestClient(app).get('/transformation-agent/api/v2/openapi.json').json()
    assert 'HTTPBearer' not in schema.get('components', {}).get('securitySchemes', {})
    assert len(schema['paths']) == 6
