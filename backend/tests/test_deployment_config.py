import pytest
from app.core.deployment import validate_environment


def test_production_env_from_configmap():
    validate_environment({'APP_ENV': 'production', 'AUTH_MODE': 'gateway',
        'GATEWAY_SHARED_SECRET': 'synthetic-test-key-' * 3,
        'DATABASE_URL': 'postgresql+psycopg://example.invalid/test',
        'CORS_ORIGINS': 'https://example.test'})


def test_all_missing_settings_reported_together():
    with pytest.raises(RuntimeError) as caught:
        validate_environment({'APP_ENV': 'production'})
    message = str(caught.value)
    for name in ('GATEWAY_SHARED_SECRET', 'DATABASE_URL', 'CORS_ORIGINS', 'envFrom'):
        assert name in message


def test_invalid_config_does_not_disclose_values():
    with pytest.raises(RuntimeError) as caught:
        validate_environment({'APP_ENV': 'production', 'GATEWAY_SHARED_SECRET': 'private-short-value'})
    assert 'private-short-value' not in str(caught.value)


def test_legacy_login_not_supported():
    with pytest.raises(RuntimeError, match='AUTH_MODE must be gateway'):
        validate_environment({'AUTH_MODE': 'legacy'})
