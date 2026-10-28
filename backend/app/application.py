"""Application composition; no transformation business logic belongs here."""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.deployment import validate_environment
from app.core.runtime_settings import RuntimeSettings


def create_application() -> FastAPI:
    from app.core.observability import configure_logging, RequestLoggingMiddleware
    configure_logging()
    # A standalone deployment never issues or accepts local login tokens.
    os.environ.setdefault('AUTH_MODE', 'gateway')
    validate_environment()
    RuntimeSettings.from_environment()
    # Validate configuration before importing database-dependent controllers.
    from app.api.contract_v2 import create_contract_app
    from app.api.transformation_handoff import router

    application = FastAPI(title='Transformation Agent', version='2.0.0')
    origins = [value.strip() for value in os.getenv('CORS_ORIGINS', '').split(',') if value.strip()]
    if origins:
        application.add_middleware(CORSMiddleware, allow_origins=origins,
                                   allow_credentials=True, allow_methods=['GET', 'POST'],
                                   allow_headers=['Content-Type', 'X-Authenticated-User', 'X-Gateway-Key', 'x-channel-name', 'x-service-id'])
    integration_api = create_contract_app([router])
    application.state.integration_api = integration_api
    application.mount('/api/v2', integration_api)

    @application.get('/health', tags=['Health'])
    def health():
        return {'st': True, 'msg': 'success', 'msgId': 'SUCCESS',
                'data': {'status': 'UP', 'service': 'transformation-agent'}}

    @application.get('/ready', tags=['Health'])
    def ready():
        from fastapi.responses import JSONResponse
        from app.services.readiness import readiness
        result = readiness()
        return JSONResponse(result, status_code=200 if result['st'] else 503)

    application.add_middleware(RequestLoggingMiddleware)
    return application
