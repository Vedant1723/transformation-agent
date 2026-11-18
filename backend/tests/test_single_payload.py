import pytest
import json
from lxml import etree
from app.transformations.payload_generator import generate_payload


@pytest.mark.parametrize('fmt', ['JSON', 'XML', 'ISO'])
@pytest.mark.parametrize('direction', ['REQUEST', 'RESPONSE'])
def test_one_payload_for_each_source_and_direction(fmt, direction):
    prefix = 'body.request' if direction == 'REQUEST' else 'body'
    ref = prefix + ('["4"]' if fmt == 'ISO' else '.amount')
    result = generate_payload('${' + ref + '?number}', fmt, direction)
    assert 'cases' not in result
    assert result['verified'] is False
    payload = result['input_payload']
    if direction == 'REQUEST':
        assert set(payload) == {'inputRequest', 'inputHeaders', 'additionalProperties'}
        payload = payload['inputRequest']
    assert isinstance(payload, dict if fmt == 'JSON' else str)


def test_list_returns_one_populated_sample():
    result = generate_payload('<#list body.request.items as item>${item.amount?number}</#list>')
    assert result['input_payload']['inputRequest']['items'] == [{'amount': 10}]
    assert 'cases' not in result


@pytest.mark.parametrize('direction', ['REQUEST', 'RESPONSE'])
@pytest.mark.parametrize('fmt', ['JSON', 'XML'])
def test_nested_and_reused_loop_aliases(direction, fmt):
    prefix = 'body.request' if direction == 'REQUEST' else 'body'
    template = ('<#list PREFIX.orders as row><#list row.items as item>'
                '${item.price?number}</#list></#list>'
                '<#list PREFIX.codes as item>${item?string}</#list>').replace('PREFIX', prefix)
    payload = generate_payload(template, fmt, direction)['input_payload']
    if direction == 'REQUEST': payload = payload['inputRequest']
    if fmt == 'JSON':
        assert payload['orders'][0]['items'][0]['price'] == 10
        assert len(payload['codes']) == 1
        json.dumps(payload)
    else:
        root = etree.fromstring(payload.encode())
        assert root.findtext('orders/items/price') == '10'
        assert root.find('codes') is not None


@pytest.mark.parametrize('direction', ['REQUEST', 'RESPONSE'])
def test_json_root_array(direction):
    prefix = 'body.request' if direction == 'REQUEST' else 'body'
    payload = generate_payload('${' + prefix + '[0].amount?number}', direction=direction)['input_payload']
    if direction == 'REQUEST':payload = payload['inputRequest']
    assert payload == [{'amount': 10}]


def test_metadata_only_and_header_aliases():
    payload = generate_payload('${body.header["x-id"]} ${body.headers.trace} ${body.addProps.region}')['input_payload']
    assert payload == {'inputRequest': {}, 'inputHeaders': {'x-id':'DEMO_x-id', 'trace':'DEMO_trace'}, 'additionalProperties':{'region':'DEMO_region'}}


def test_response_preserves_fields_named_like_metadata():
    payload = generate_payload('${body.headers.code} ${body.request.amount?number}', direction='RESPONSE')['input_payload']
    assert payload == {'headers':{'code':'DEMO_code'}, 'request':{'amount':10}}


def test_xml_attributes_are_valid_xml():
    payload = generate_payload('${body.request.payment["@id"]} ${body.request.payment.amount?number}', 'XML')['input_payload']['inputRequest']
    root = etree.fromstring(payload.encode())
    assert root.find('payment').get('id') == 'DEMO_@id'
    assert root.findtext('payment/amount') == '10'


@pytest.mark.parametrize('template', [
    '${body.request.items[10].amount}',
    '${body.request.items[0].amount} ${body.request.items.name}',
    '<#list body.request.items?filter(x -> x.active) as item>${item.name}</#list>',
    '<#list body.request.items as item>${item.name}',
    '</#list>',
])
def test_unsupported_structures_fail_clearly(template):
    with pytest.raises(ValueError): generate_payload(template)


@pytest.mark.parametrize('fmt,direction', [('YAML','REQUEST'), ('JSON','OTHER')])
def test_reject_unknown_options(fmt, direction):
    with pytest.raises(ValueError): generate_payload('${body.amount}', fmt, direction)


def test_iso_rejects_nested_objects():
    with pytest.raises(ValueError): generate_payload('${body["4"].value}', 'ISO', 'RESPONSE')
