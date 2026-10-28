from fastapi.testclient import TestClient
from app.main import app


def test_service_context_path():
    client = TestClient(app)
    assert client.get('/transformation-agent/health').json()['st'] is True
    assert client.get('/transformation-agent/api/v2/health').status_code == 200
    schema = client.get('/transformation-agent/api/v2/openapi.json')
    assert schema.status_code == 200
    assert '/transformations/generate' in schema.json()['paths']
    assert client.get('/transformation-agent/api/v2/docs').status_code == 200
    assert client.get('/health').status_code == 404
    assert client.get('/api/v2/health').status_code == 404


def test_prefixed_readiness(monkeypatch):
    from app.services import readiness
    monkeypatch.setattr(readiness, 'readiness', lambda: {'st': True})
    assert TestClient(app).get('/transformation-agent/ready').status_code == 200
