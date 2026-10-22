"""Fail closed for explicitly production-configured application startup."""
import os


def validate_environment(env=None):
    env=os.environ if env is None else env
    if env.get('AUTH_MODE','legacy') not in ('legacy','gateway'):
        raise RuntimeError('AUTH_MODE must be legacy or gateway.')
    if env.get('APP_ENV','development').lower()!='production':return
    if env.get('AUTH_MODE')=='gateway':
        if len(env.get('GATEWAY_SHARED_SECRET','').encode())<32:
            raise RuntimeError('Gateway production requires GATEWAY_SHARED_SECRET of at least 32 bytes.')
    secret=env.get('JWT_SECRET_KEY','')
    if env.get('AUTH_MODE')!='gateway' and (len(secret.encode('utf-8'))<32 or secret=='dev-only-change-this-secret'):
        raise RuntimeError('Production requires an explicit JWT_SECRET_KEY of at least 32 bytes.')
    if not env.get('DATABASE_URL','').strip():
        raise RuntimeError('Production requires an explicit DATABASE_URL.')
    origins=[value.strip() for value in env.get('CORS_ORIGINS','').split(',') if value.strip()]
    if not origins or '*' in origins:
        raise RuntimeError('Production requires explicit CORS_ORIGINS without a wildcard.')
