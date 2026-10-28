"""Run from backend: python -m pytest tests -q (no database/Java needed)."""
from fastapi.testclient import TestClient
from app.main import app
from app.schemas.transformations import TransformationTestRequest
from app.transformations.payload_generator import generate_payload


def test_minimal_public_surface():
    client=TestClient(app)
    paths=client.get('/transformation-agent/api/v2/openapi.json').json()['paths']
    assert len(paths)==6
    assert client.post('/api/v1/auth/login').status_code==404
    assert client.get('/transformation-agent/api/v2/health').json()['st'] is True


def test_request_envelope():
    request=TransformationTestRequest(direction='REQUEST',template='x',input_payload={
        'inputRequest':'{"amount":25}','headers':{'trace':'DEMO'},'additionalProperties':{}})
    assert request.input_payload=={'amount':25}
    assert request.headers=={'trace':'DEMO'}


def test_payload_generator():
    case=generate_payload('${body.request.amount?c} ${body.headers.trace}')['cases'][0]
    assert case['input_payload']['inputRequest']=={'amount':10}
    assert case['input_payload']['headers']=={'trace':'DEMO_trace'}
