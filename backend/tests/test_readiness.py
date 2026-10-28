from fastapi.testclient import TestClient
from app.main import app
from app.services import readiness


def test_ready_preserves_503(monkeypatch):
    monkeypatch.setattr(readiness, 'readiness', lambda: {'st': False, 'msg': 'failure',
        'msgId': 'SERVICE_UNAVAILABLE', 'data': {'ready': False}})
    response = TestClient(app).get('/transformation-agent/ready')
    assert response.status_code == 503
    assert response.json()['st'] is False


def test_ready_success(monkeypatch):
    monkeypatch.setattr(readiness, 'readiness', lambda: {'st': True, 'msg': 'success',
        'msgId': 'SUCCESS', 'data': {'ready': True}})
    assert TestClient(app).get('/transformation-agent/ready').status_code == 200
