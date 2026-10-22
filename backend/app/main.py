"""ASGI entry point: uvicorn app.main:app."""
from app.application import create_application

app = create_application()
