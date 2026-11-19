import pytest
from app.transformations.payload_generator import generate_payload
from app.transformations.workbench import generate, normalize, literal
from app.schemas.transformations import TransformationChatRequest
from app.transformations.payload_scenarios import Condition, NUMERIC_PATTERN
from test_generation_acceptance import client


@pytest.mark.parametrize('direction',['REQUEST','RESPONSE'])
@pytest.mark.parametrize('fmt',['JSON','XML','ISO'])
def test_typed_chains(direction,fmt):
    prefix='body.request' if direction=='REQUEST' else 'body'
    boolean=prefix+'["48"]' if fmt=='ISO' else prefix+'.flag'
    numeric=prefix+'["4"]' if fmt=='ISO' else prefix+'.value'
    template='${'+boolean+'?string?boolean?c} ${'+numeric+'?string?trim?number?c}'
    result=generate_payload(template,fmt,direction)['input_payload']
    if direction=='REQUEST':result=result['inputRequest']
    if fmt=='JSON':assert result=={'flag':True,'value':10}
    elif fmt=='ISO':assert '48=true' in result and '4=10' in result
    else:assert '<flag>true</flag>' in result and '<value>10</value>' in result


def test_boolean_c_and_conflicting_types():
    assert generate_payload('${body.active?c}',direction='RESPONSE')['input_payload']['active'] is True
    with pytest.raises(ValueError,match='both boolean and number'):
        generate_payload('${body.flag?boolean?c} ${body.flag?number?c}',direction='RESPONSE')


def test_xml_comments_are_not_mapping_fields():
    assert normalize('<Payment><!--note--><?sample ignore?><amount>25</amount></Payment>','XML')=={'Payment':{'amount':'25'}}


@pytest.mark.parametrize('side',['source','target'])
def test_ambiguous_paths_return_422(client,side):
    body={'direction':'RESPONSE','source':{'amount':25},'target':{'amount':0}}
    body[side]={'a.b':1,'a':{'b':2}}
    response=client.post('/transformation-agent/api/v2/transformations/generate',json=body)
    assert response.status_code==422
    assert 'ambiguous dotted field path' in response.text


@pytest.mark.parametrize('fmt',['JSON','XML'])
def test_compiled_numeric_conditions_generate_both_scenarios(fmt):
    source={'amount':25} if fmt=='JSON' else '<Payment><amount>25</amount></Payment>'
    field='amount' if fmt=='JSON' else 'Payment.amount'
    request=TransformationChatRequest.model_validate({'direction':'RESPONSE','type':fmt+'TOJSON','source':source,
        'target':{'status':''},'conditions':[{'target':'status','branches':[{'field':field,'operator':'gte','value':20,'then':'OK'}],'else':'LOW'}]})
    template=generate(request)['template']
    result=generate_payload(template,fmt,'RESPONSE','Payment')
    assert len(result['input_scenarios'])==2,result['warnings']
    assert not any('branches need manual' in w for w in result['warnings'])


def test_xml_node_size_and_empty_element_semantics():
    assert Condition('body.amount?size == 1').evaluate(lambda ref:'1000','XML') is True
    assert Condition('body.name?has_content').evaluate(lambda ref:'','XML') is True


def test_numeric_guard_does_not_accept_arbitrary_regex():
    with pytest.raises(ValueError):Condition('body.value?matches("(a+)+$")')
    condition=Condition('body.value?string?matches("'+NUMERIC_PATTERN+'")')
    assert condition.evaluate(lambda ref:'1e5') is True
    assert condition.evaluate(lambda ref:'not-a-number') is False


def test_literal_interpolation_markers_are_split_not_backslash_escaped():
    encoded=literal('text ${partner} #{reference}')
    assert '${' not in encoded and '#{' not in encoded
    assert '\\$' not in encoded and '\\#' not in encoded
