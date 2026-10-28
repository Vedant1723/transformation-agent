"""Validate settings injected by Kubernetes ConfigMap/envFrom.

No deployment credentials or cluster addresses belong in this module.
"""
import os


def validate_environment(env=None):
    env = os.environ if env is None else env
    errors = []
    mode = env.get('AUTH_MODE', 'gateway')
    if mode not in ('gateway', 'ingress'):
        errors.append('AUTH_MODE must be gateway or ingress')
    if mode == 'ingress':
        for key in ('INGRESS_CHANNEL_NAME', 'INGRESS_SERVICE_ID', 'INGRESS_SHARED_SUBJECT'):
            value = env.get(key, '')
            if not value or value != value.strip() or len(value) > 100 or any(ord(c) < 32 or ord(c) > 126 for c in value):
                errors.append(key + ' must contain 1-100 printable ASCII characters without surrounding whitespace')
    if env.get('APP_ENV', 'development').lower() == 'production':
        if mode == 'gateway' and len(env.get('GATEWAY_SHARED_SECRET', '').encode('utf-8')) < 32:
            errors.append('GATEWAY_SHARED_SECRET must contain at least 32 UTF-8 bytes')
        if not env.get('DATABASE_URL', '').strip():
            errors.append('DATABASE_URL is required')
        origins = [value.strip() for value in env.get('CORS_ORIGINS', '').split(',') if value.strip()]
        if not origins or '*' in origins:
            errors.append('CORS_ORIGINS must contain explicit approved origins (no wildcard)')
    if errors:
        raise RuntimeError(
            'Invalid deployment environment: ' + '; '.join(errors) + '. '
            'Set these keys directly under data in transformation-agent-config, '
            'reference it through container envFrom.configMapRef, and restart the pods. '
            'Mounted application.properties files are not read by this Python service.'
        )
