import pytest
from app.transformations.payload_generator import generate_payload
from app.schemas.transformations import TransformationTestRequest
from app.transformations.input_envelope import unpack


@pytest.mark.parametrize('fmt', ['JSON','XML','ISO'])
def test_generated_envelope_can_be_tested(fmt):
    field = '["4"]' if fmt == 'ISO' else '.amount'
    template = '${body.request' + field + '?number} ${body.header.trace} ${body.addProps.region}'
    result = generate_payload(template, fmt, 'REQUEST')['input_payload']
    assert result['inputHeaders'] == {'trace':'DEMO_trace'}
    assert 'headers' not in result
    request = TransformationTestRequest(template=template, direction='REQUEST', source_format=fmt, input_payload=result)
    assert request.headers == {'trace':'DEMO_trace'}
    assert request.additionalProperties == {'region':'DEMO_region'}
    assert request.input_payload == result['inputRequest']


def test_legacy_and_conflicts():
    assert unpack({'inputRequest':{}, 'headers':{'x':'old'}},'REQUEST')[2] == {'x':'old'}
    with pytest.raises(ValueError):unpack({'inputRequest':{},'inputHeaders':{'x':'new'},'headers':{'x':'old'}},'REQUEST')
    with pytest.raises(ValueError):unpack({'inputRequest':{},'inputHeaders':[]},'REQUEST')
    with pytest.raises(ValueError):unpack({'inputRequest':{},'inputHeaders':{'x':'new'}},'REQUEST',headers={'x':'old'})


def test_response_is_not_unwrapped():
    value={'inputRequest':{}, 'inputHeaders':{'x':'business-field'}}
    assert unpack(value,'RESPONSE')[0] == value
