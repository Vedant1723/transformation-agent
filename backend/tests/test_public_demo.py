from fastapi.testclient import TestClient
from app.public_demo import app

client = TestClient(app)
BASE = '/transformation-agent'


def test_anonymous_generation():
    response = client.post(BASE + '/api/v2/transformations/generate', json={
        'direction': 'REQUEST', 'source': {'payload': {'amount': 25}},
        'target': {'payload': {'amount': 0}}})
    assert response.status_code == 200
    assert response.json()['data']['persisted'] is False
    assert 'template' in response.json()['data']


def test_privileged_routes_absent():
    for path in ('feedback', 'test', 'model', 'training'):
        assert client.post(BASE + '/api/v2/transformations/' + path, json={}).status_code == 404
        assert client.get(BASE + '/api/v2/transformations/' + path).status_code == 404


def test_oversize_rejected():
    assert client.post(BASE + '/api/v2/transformations/generate', content=b'x'*32769).status_code == 422


def test_anonymous_payload():
    response = client.post(BASE + '/api/v2/transformations/tools', json={
        'action': 'generate_payload', 'template': '${body.request.amount?c}'})
    assert response.status_code == 200
    assert response.json()['st'] is True
