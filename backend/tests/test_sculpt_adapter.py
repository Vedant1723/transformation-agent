import httpx
import pytest
from app.core.runtime_settings import RuntimeSettings
from app.transformations.runtime_client import FreeMarkerRuntimeClient


@pytest.fixture
def client():
    return FreeMarkerRuntimeClient(settings=RuntimeSettings(protocol='sculpt', base_url='https://example.test', bearer_token='synthetic-token'))


def capture(monkeypatch, payload):
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, json=payload, request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx, 'post', post)
    return calls


def test_request_contract(client, monkeypatch):
    calls = capture(monkeypatch, {'st': True, 'data': '{"test":"value"}'})
    result = client.execute('template', {'test': 'value'}, 'REQUEST', {'prop': 'p'}, {'header': 'h'})
    assert calls[0][0].endswith('/sculpt/template/validate/v3')
    assert calls[0][1]['json'] == {'type': 'JSONTOJSON', 'template': 'template', 'input': {
        'inputRequest': {'test': 'value'}, 'inputHeaders': {'header': 'h'}, 'additionalProperties': {'prop': 'p'}}}
    assert calls[0][1]['headers']['Authorization'] == 'Bearer synthetic-token'
    assert result == {'success': True, 'output': '{"test":"value"}'}


@pytest.mark.parametrize('expected', [None, '', '{"total":25}', {'total': 25}])
def test_response_contract(client, monkeypatch, expected):
    calls = capture(monkeypatch, {'st': True, 'data': '{"total":25}'})
    client.execute('template', {'amount': 25}, 'RESPONSE', ideal_object=expected)
    assert calls[0][0].endswith('/sculpt/template/validate/v2')
    assert calls[0][1]['json'] == {'type': 'JSONTOJSON', 'template': 'template',
        'responseObj': {'amount': 25}, 'idealObject': '', 'input': {'additionalProperties': {}}}


@pytest.mark.parametrize('source,target', [('JSON','XML'),('XML','JSON'),('XML','XML'),('ISO','JSON')])
def test_format_forwarding(client, monkeypatch, source, target):
    calls = capture(monkeypatch, {'st': True, 'data': 'output'})
    client.execute('template', '<root/>', 'REQUEST', source_format=source, target_format=target)
    assert calls[0][1]['json']['type'] == source+'TO'+target
    assert calls[0][1]['json']['input']['inputRequest'] == '<root/>'


def test_failure(client, monkeypatch):
    capture(monkeypatch, {'st': False, 'validationError': 'Missing amount'})
    assert client.execute('template', {})['error'] == 'Missing amount'


@pytest.mark.parametrize('payload', [{}, {'st':'true','data':'{}'}, {'st':True,'data':{}}])
def test_bad_contract(client, monkeypatch, payload):
    capture(monkeypatch, payload)
    with pytest.raises(httpx.HTTPStatusError):
        client.execute('template', {})


def test_health_does_not_call_network(client, monkeypatch):
    monkeypatch.setattr(httpx, 'get', lambda *a, **k: pytest.fail('No Java health request allowed'))
    assert client.health()['status'] == 'NOT_CHECKED'


def test_readiness_does_not_call_java(monkeypatch):
    from app.services import readiness
    monkeypatch.setattr(httpx, 'get', lambda *a, **k: pytest.fail('No Java health request allowed'))
    result = readiness.readiness()
    assert result['data']['java_execution'] == 'not_checked'
    assert 'java_execution' not in result['data']['checks']
