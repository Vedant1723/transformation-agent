from types import SimpleNamespace
import pytest
from starlette.requests import Request
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.core.deployment import validate_environment
from app.core.gateway_identity import gateway_user


@pytest.fixture
def ingress(monkeypatch):
    settings = {'AUTH_MODE': 'ingress', 'INGRESS_CHANNEL_NAME': 'demo-channel',
                'INGRESS_SERVICE_ID': 'demo-service', 'INGRESS_SHARED_SUBJECT': 'shared'}
    for key, value in settings.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv('GATEWAY_SHARED_SECRET', raising=False)
    return settings


def req(headers):
    return Request({'type': 'http', 'headers': [(k.encode(), v.encode()) for k, v in headers]})


HEADERS = [('x-channel-name', 'demo-channel'), ('x-service-id', 'demo-service')]


def test_no_secret_required_at_startup(ingress):
    validate_environment({**ingress, 'APP_ENV': 'production',
        'DATABASE_URL': 'sqlite://', 'CORS_ORIGINS': 'https://example.test'})


def test_shared_identity_without_gateway_key(ingress):
    observed = []
    user = SimpleNamespace(id=7)
    def lookup(statement):
        observed.append(statement.compile().params)
        return user
    assert gateway_user(req(HEADERS + [('x-authenticated-user', 'spoofed')]), SimpleNamespace(scalar=lookup)) is user
    assert 'shared' in observed[0].values()
    assert 'spoofed' not in observed[0].values()


@pytest.mark.parametrize('headers', [[], HEADERS[:1],
    [('x-channel-name', 'wrong'), HEADERS[1]], HEADERS + [HEADERS[0]]])
def test_invalid_headers_rejected(ingress, headers):
    with pytest.raises(HTTPException) as caught:
        gateway_user(req(headers), None)
    assert caught.value.status_code == 403


def test_unknown_or_inactive_shared_user_rejected(ingress):
    with pytest.raises(HTTPException) as caught:
        gateway_user(req(HEADERS), SimpleNamespace(scalar=lambda _: None))
    assert caught.value.status_code == 403


def test_missing_configuration_rejected():
    with pytest.raises(RuntimeError, match='INGRESS_CHANNEL_NAME'):
        validate_environment({'AUTH_MODE': 'ingress'})


def test_ingress_application_creation(ingress):
    from app.application import create_application
    assert TestClient(create_application()).get('/health').status_code == 200
