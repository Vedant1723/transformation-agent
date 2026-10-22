"""Real Java execution acceptance; set RUN_JAVA_ACCEPTANCE=1 to opt in."""
import hashlib
import json
import os
from pathlib import Path
import httpx
import pytest
from lxml import etree
from test_generation_acceptance import client

pytestmark = pytest.mark.skipif(os.getenv('RUN_JAVA_ACCEPTANCE') != '1', reason='Requires external Java test renderer')


@pytest.fixture(autouse=True)
def execution_service():
    response = httpx.get(os.getenv('JAVA_RUNTIME_URL', 'http://localhost:8090') + '/health', timeout=3)
    response.raise_for_status()


def post(client, operation, body, status=200):
    response = client.post('/api/v2/transformations/' + operation, json=body)
    assert response.status_code == status, response.text
    result = response.json()
    assert set(result) == {'st', 'msg', 'msgId', 'data'}
    assert result['st'] is True, result
    return result['data']


def render(client, template, payload, sf='JSON', tf='JSON', direction='REQUEST'):
    return post(client, 'test', {'template': template, 'input_payload': payload,
        'source_format': sf, 'target_format': tf, 'direction': direction})


@pytest.mark.parametrize('direction', ['REQUEST', 'RESPONSE'])
@pytest.mark.parametrize('sf', ['JSON', 'XML', 'ISO'])
@pytest.mark.parametrize('tf', ['JSON', 'XML', 'ISO'])
def test_format_matrix_and_generated_payload(client, direction, sf, tf):
    source = {'JSON': {'amount': 25}, 'XML': '<payment><amount>25</amount></payment>', 'ISO': '4=25'}[sf]
    target = {'JSON': {'total': 0}, 'XML': '<Payment><total>0</total></Payment>', 'ISO': '4=0'}[tf]
    source_path = {'JSON': 'amount', 'XML': 'payment.amount', 'ISO': '4'}[sf]
    target_path = {'JSON': 'total', 'XML': 'Payment.total', 'ISO': '4'}[tf]
    context = {'direction': direction, 'source': {'format': sf, 'payload': source},
        'target': {'format': tf, 'payload': target}, 'mappings': {target_path: source_path}}
    template = post(client, 'generate', context)['template']
    result = render(client, template, source, sf, tf, direction)
    assert result['passed'], result
    if tf == 'JSON': assert json.loads(result['output'])['total'] == 25
    elif tf == 'XML': assert etree.fromstring(result['output'].encode()).findtext('total') == '25'
    else: assert '4=25' in result['output']
    samples = post(client, 'tools', {'action': 'generate_payload', 'template': template,
        'source_format': sf, 'direction': direction, 'xml_root': 'payment'})
    result = render(client, template, samples['cases'][0]['input_payload'], sf, tf, direction)
    assert result['passed'], {'sample': samples, 'render': result}


@pytest.mark.parametrize('kind,value,valid,invalid', [
    ('required', '', 'x', ''), ('min', 10, 12, 9), ('max', 20, 12, 21),
    ('length', 3, 'abc', 'ab'), ('min_length', 2, 'abc', 'a'), ('max_length', 3, 'abc', 'abcd'),
    ('regex', '[A-Z]{3}', 'KES', '123'), ('enum', 'KES,USD', 'KES', 'TZS'),
    ('email', '', 'a@example.com', 'invalid'), ('type', 'number', 12, 'text')])
def test_validation_pass_and_fail(client, kind, value, valid, invalid):
    data = post(client, 'generate', {'direction': 'REQUEST', 'source': {'payload': {'field': valid}},
        'target': {'payload': {'field': ''}}, 'validations': [{'field': 'field', 'type': kind, 'value': value}]})
    assert render(client, data['template'], {'field': valid})['passed']
    failed = render(client, data['template'], {'field': invalid})
    assert not failed['passed'], failed
    assert failed['error']


def test_feedback_approval_and_weights_unchanged(client):
    checkpoint = Path(__file__).resolve().parents[2] / 'model-runs/expanded-resume-20260921-114948/checkpoint.pt'
    before = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    context = {'direction': 'REQUEST', 'source': {'payload': {'name': 'Alice'}},
        'target': {'payload': {'fullName': ''}}, 'mappings': {'fullName': 'name'}}
    template = post(client, 'generate', context)['template']
    feedback = post(client, 'feedback', {'context': context, 'template': template,
        'expected_output': '{"fullName":"Alice"}', 'approved': True, 'sanitized': True,
        'validation_cases': [{'name': 'second name', 'input_payload': {'name': 'Bob'},
                              'expected_output': '{"fullName":"Bob"}'}]}, status=201)
    assert feedback['dataset_eligible'], feedback
    assert feedback['active_model_learning_confirmed'] is False
    assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == before


def test_diagnose_invalid_template(client):
    result = render(client, '<#if true>{}', {})
    assert not result['passed']
    assert result['stage'] == 'runtime'
    assert result['error']


def test_collections_empty_and_special_characters(client):
    context = {'direction': 'REQUEST', 'source': {'payload': {'items': [{'name': 'A & "B"'}, {'name': 'C'}]}},
        'target': {'payload': {'items': [{'name': ''}]}}}
    template = post(client, 'generate', context)['template']
    for items in (context['source']['payload']['items'], []):
        result = render(client, template, {'items': items})
        assert result['passed'], result
        assert json.loads(result['output']) == {'items': items}


@pytest.mark.parametrize('sf', ['JSON', 'XML'])
@pytest.mark.parametrize('tf', ['JSON', 'XML'])
def test_cross_format_collections(client, sf, tf):
    source = {'items': [{'code': 'A'}, {'code': 'B'}]} if sf == 'JSON' else '<root><items><item><code>A</code></item><item><code>B</code></item></items></root>'
    target = {'items': [{'code': ''}]} if tf == 'JSON' else '<out><items><item><code/></item></items></out>'
    template = post(client, 'generate', {'direction': 'REQUEST', 'source': {'format': sf, 'payload': source},
        'target': {'format': tf, 'payload': target}})['template']
    result = render(client, template, source, sf, tf)
    assert result['passed'], result
    codes = [row['code'] for row in json.loads(result['output'])['items']] if tf == 'JSON' else etree.fromstring(result['output'].encode()).xpath('//code/text()')
    assert codes == ['A', 'B']


def test_request_metadata_and_tools(client):
    template = '<#assign body=JsonUtils.getJsonAsMap(input)>{"amount":${body.request.amount?c},"trace":"${body.headers.trace?json_string}","partner":"${body.addProps.partner?json_string}"}'
    payload = {'inputRequest': {'amount': 25}, 'headers': {'trace': 'T1'}, 'additionalProperties': {'partner': 'DEMO'}}
    result = render(client, template, payload)
    assert result['passed'], result
    assert json.loads(result['output']) == {'amount': 25, 'trace': 'T1', 'partner': 'DEMO'}
    post(client, 'tools', {'action': 'inspect', 'template': template})
    revised = post(client, 'tools', {'action': 'revise', 'template': template, 'replacements': [{'find': '"amount":', 'replace': '"total":'}]})
    post(client, 'tools', {'action': 'compare', 'template': template, 'other_template': revised['template']})
    assert json.loads(render(client, revised['template'], payload)['output'])['total'] == 25


def test_feedback_wrong_expected_output_is_not_approved(client):
    context = {'direction': 'REQUEST', 'source': {'payload': {'amount': 25}}, 'target': {'payload': {'amount': 0}}}
    template = post(client, 'generate', context)['template']
    feedback = post(client, 'feedback', {'context': context, 'template': template,
        'expected_output': '{"amount":999}', 'approved': True, 'sanitized': True}, status=201)
    assert feedback['status'] == 'validation_failed'
    assert not feedback['test']['mapping_passed']
