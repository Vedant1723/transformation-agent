"""Real agent and persistence tests. Java execution is tested separately."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.main import app
from app.core.auth import get_current_user
from app.database.session import get_db
from app.database.base import Base
from app.models.user import UserModel


@pytest.fixture
def client():
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        user = UserModel(username='synthetic', email='synthetic@example.test', password_hash='!disabled')
        db.add(user)
        db.commit()
        api = app.state.integration_api
        api.dependency_overrides[get_current_user] = lambda: user
        api.dependency_overrides[get_db] = lambda: db
        try:
            with TestClient(app) as client:
                yield client
        finally:
            api.dependency_overrides.clear()
    engine.dispose()


SAMPLES = {'JSON': {'amount': 25}, 'XML': '<payment><amount>25</amount></payment>', 'ISO': '4=25'}
TARGETS = {'JSON': {'total': 0}, 'XML': '<Payment><total>0</total></Payment>', 'ISO': '4=0'}


@pytest.mark.parametrize('source_format', SAMPLES)
@pytest.mark.parametrize('target_format', TARGETS)
def test_generate_all_format_pairs(client, source_format, target_format):
    response = client.post('/transformation-agent/api/v2/transformations/generate', json={
        'direction': 'RESPONSE', 'source': {'format': source_format, 'payload': SAMPLES[source_format]},
        'target': {'format': target_format, 'payload': TARGETS[target_format]}})
    assert response.status_code == 200, response.text
    assert response.json()['data']['template'].strip()
    assert response.json()['data']['learning_id'] > 0


def test_listing_and_payload_generation(client):
    response = client.post('/transformation-agent/api/v2/transformations/generate', json={
        'direction': 'REQUEST',
        'source': {'payload': {'items': [{'code': 'A', 'quantity': 2}, {'code': 'B', 'quantity': 3}]}},
        'target': {'payload': {'items': [{'code': '', 'quantity': 0}]}}})
    assert response.status_code == 200, response.text
    template = response.json()['data']['template']
    assert '<#list' in template
    response = client.post('/transformation-agent/api/v2/transformations/tools', json={
        'action': 'generate_payload', 'template': template, 'direction': 'REQUEST'})
    assert response.status_code == 200, response.text
    assert response.json()['data']['cases']


def test_metadata_conflict_rejected(client):
    response = client.post('/transformation-agent/api/v2/transformations/test', json={
        'direction': 'REQUEST', 'template': 'example', 'headers': {'trace': 'one'},
        'input_payload': {'inputRequest': {}, 'headers': {'trace': 'two'}}})
    assert response.status_code == 422
