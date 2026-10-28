"""ASGI entry point with the public service context path."""
from fastapi import FastAPI
from app.application import create_application

CONTEXT_PATH = '/transformation-agent'

# Mount the complete service so APIs, documentation and probes share a prefix.
# The ingress must preserve this path (no prefix-stripping rewrite).
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
service = create_application()
app.state.integration_api = service.state.integration_api
app.mount(CONTEXT_PATH, service)
