import json
import pytest
from test_generation_acceptance import client
from app.transformations.structure import choose

URL = '/transformation-agent/api/v2/transformations/generate'
PAYLOADS = {'JSON': {'amount':25}, 'XML':'<payment><amount>25</amount></payment>', 'ISO':'4=25'}


@pytest.mark.parametrize('direction', ['REQUEST','RESPONSE'])
@pytest.mark.parametrize('source_format', PAYLOADS)
@pytest.mark.parametrize('target_format', PAYLOADS)
@pytest.mark.parametrize('stringified', [False,True])
def test_simple_contract(client, direction, source_format, target_format, stringified):
    source = PAYLOADS[source_format]
    target = PAYLOADS[target_format]
    if stringified:
        if source_format == 'JSON':source = json.dumps(source)
        if target_format == 'JSON':target = json.dumps(target)
    result = client.post(URL, json={'direction':direction,'type':source_format+'TO'+target_format,
                                  'source':source, 'target':target})
    assert result.status_code == 200, result.text
    data = result.json()['data']
    assert data['template']
    assert data['request']['source']['format'] == source_format
    assert data['request']['target']['format'] == target_format
    assert any(row['source_field'] for row in data['mappings'])
    if source_format == 'JSON':assert data['request']['source']['payload'] == {'amount':25}


def test_automatic_format_detection(client):
    result = client.post(URL, json={'direction':'RESPONSE',
        'source':'{"amount":25}', 'target':'<payment><amount>0</amount></payment>'})
    assert result.status_code == 200, result.text
    assert result.json()['data']['request']['target']['format'] == 'XML'


def test_envelope_with_json_string(client):
    result = client.post(URL, json={'direction':'REQUEST','type':'JSONTOJSON',
        'source':{'inputRequest':'{"amount":25}', 'headers':{'trace':'abc'}, 'additionalProperties':{'region':'UG'}},
        'target':{'amount':0}})
    assert result.status_code == 200, result.text
    request = result.json()['data']['request']
    assert request['source']['payload'] == {'amount':25}
    assert request['headers'] == {'trace':'abc'}


@pytest.mark.parametrize('source', ['{"amount":}', '{"amount":1,"amount":2}', '<payment/>'])
def test_bad_json_or_mismatched_type(client, source):
    result = client.post(URL, json={'direction':'RESPONSE','type':'JSONTOJSON','source':source,'target':{'amount':0}})
    assert result.status_code == 422


def test_conflicting_wrapper_format(client):
    result = client.post(URL, json={'direction':'RESPONSE','type':'XMLTOJSON',
        'source':{'format':'JSON','payload':{'amount':1}}, 'target':{'amount':0}})
    assert result.status_code == 422


def test_mapping_separators_and_ambiguity():
    assert choose(('fullName',), {'full_name':(('full_name',),'Alice')})[0] == 'full_name'
    assert choose(('fullName',), {'a.full_name':(('a','full_name'),'Alice'), 'b.fullName':(('b','fullName'),'Bob')})[0] == ''


def test_exact_frontend_example(client):
    result = client.post(URL, json={
        'direction':'REQUEST', 'type':'JSONTOXML',
        'source':{'name':'Alice','amount':25},
        'target':'<Payment><fullName></fullName><amount>0</amount></Payment>'})
    assert result.status_code == 200, result.text
    assert result.json()['st'] is True
    assert 'body.request.name' in result.json()['data']['template']


def test_validation_error_explains_missing_field(client):
    result = client.post(URL, json={'direction':'REQUEST','source':{'name':'Alice'}})
    assert result.status_code == 422
    errors = result.json()['data']['detail']
    assert any(e['loc'] == ['body','target'] and e['msg'] == 'Required field is missing.' for e in errors)
    assert 'Alice' not in result.text
