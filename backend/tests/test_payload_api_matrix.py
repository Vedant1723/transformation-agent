"""Exercise generation and sample inference through the real API and SQLite."""
import json
import pytest
from lxml import etree
from test_generation_acceptance import client, SAMPLES, TARGETS


@pytest.mark.parametrize('direction', ['REQUEST', 'RESPONSE'])
@pytest.mark.parametrize('source_format', ['JSON', 'XML', 'ISO'])
@pytest.mark.parametrize('target_format', ['JSON', 'XML', 'ISO'])
def test_generate_then_sample(client, direction, source_format, target_format):
    base = '/transformation-agent/api/v2/transformations/'
    generated = client.post(base + 'generate', json={
        'direction': direction,
        'source': {'format': source_format, 'payload': SAMPLES[source_format]},
        'target': {'format': target_format, 'payload': TARGETS[target_format]},
        'mappings': {{'JSON':'total', 'XML':'Payment.total', 'ISO':'4'}[target_format]:
                     {'JSON':'amount', 'XML':'payment.amount', 'ISO':'4'}[source_format]},
    })
    assert generated.status_code == 200, generated.text
    result = client.post(base + 'tools', json={
        'action': 'generate_payload', 'direction': direction,
        'type': source_format + 'TO' + target_format, 'xml_root': 'payment',
        'template': generated.json()['data']['template'],
    })
    assert result.status_code == 200, result.text
    response = result.json()
    assert set(response) == {'st', 'msg', 'msgId', 'data'}
    assert response['st'] is True
    data = response['data']
    assert data['source_format'] == source_format
    assert 'cases' not in data
    assert data['verified'] is False
    payload = data['input_payload']
    if direction == 'REQUEST':
        assert set(payload) == {'inputRequest', 'inputHeaders', 'additionalProperties'}
        payload = payload['inputRequest']
    if source_format == 'JSON':
        assert isinstance(payload, dict)
        assert json.loads(json.dumps(payload)) == payload
    elif source_format == 'XML':
        assert etree.fromstring(payload.encode()).tag == 'payment'
    else:
        assert all(line.split('=', 1)[0].isdigit() for line in payload.splitlines())


@pytest.mark.parametrize('extra', [
    {'type': 'YAMLTOJSON'}, {'type': ''}, {'type': 123},
    {'type': 'XMLTOJSON', 'source_format': 'JSON'},
])
def test_invalid_type_rejected(client, extra):
    result = client.post('/transformation-agent/api/v2/transformations/tools', json={
        'action': 'generate_payload', 'template': '${body.request.amount?number}', **extra})
    assert result.status_code == 422
    assert result.json()['st'] is False


def test_legacy_source_format_still_works(client):
    result = client.post('/transformation-agent/api/v2/transformations/tools', json={
        'action': 'generate_payload', 'source_format': 'XML',
        'template': '${body.request.amount?number}'})
    assert result.status_code == 200
    assert etree.fromstring(result.json()['data']['input_payload']['inputRequest'].encode()).tag == 'root'
