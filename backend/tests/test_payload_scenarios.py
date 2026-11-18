import pytest
from lxml import etree
from app.transformations.payload_generator import generate_payload
from app.transformations.payload_scenarios import Condition
from test_generation_acceptance import client


@pytest.mark.parametrize('direction',['REQUEST','RESPONSE'])
@pytest.mark.parametrize('fmt',['JSON','XML','ISO'])
def test_three_branch_chain(direction,fmt):
    prefix='body.request' if direction=='REQUEST' else 'body'
    ref=prefix+'["39"]' if fmt=='ISO' else prefix+'.status'
    template='<#if REF == "200">ok<#elseif REF == "400">bad<#else>other</#if>'.replace('REF',ref)
    result=generate_payload(template,fmt,direction,'COMMAND')
    assert 'input_payload' in result and 'cases' not in result
    assert [s['name'].split(':')[0] for s in result['input_scenarios']] == ['If condition','Else-if condition','Else branch']
    values=[]
    for scenario in result['input_scenarios']:
        assert set(scenario) == {'name','input_payload'}
        payload=scenario['input_payload']
        if direction=='REQUEST':
            assert set(payload)=={'inputRequest','inputHeaders','additionalProperties'}
            payload=payload['inputRequest']
        if fmt=='JSON':values.append(payload['status'])
        elif fmt=='XML':values.append(etree.fromstring(payload.encode()).findtext('status'))
        else:values.append(payload.split('=',1)[1])
    assert values[:2]==['200','400']
    assert values[2] not in ('200','400')
    assert 'scenario_coverage' not in result
    assert not any('manual test inputs' in w for w in result['warnings'])


def test_nested_conditions_preserve_parent_and_metadata():
    template='<#if body.request.amount?number gte 10><#if body.headers.channel == "WEB">a<#else>b</#if><#else>c</#if>'
    result=generate_payload(template)
    probes=result['input_scenarios']
    assert len(probes)==4
    assert float(probes[1]['input_payload']['inputRequest']['amount'])>=10
    assert probes[1]['input_payload']['inputHeaders']['channel']=='WEB'
    assert float(probes[2]['input_payload']['inputRequest']['amount'])>=10
    assert probes[2]['input_payload']['inputHeaders']['channel']!='WEB'
    assert float(probes[3]['input_payload']['inputRequest']['amount'])<10


@pytest.mark.parametrize('condition',['body.name??','body.name?has_content','(body.name)??'])
def test_missing_field_alternative(condition):
    result=generate_payload('<#if '+condition+'>yes<#else>no</#if>',direction='RESPONSE')
    assert len(result['input_scenarios'])==2
    assert 'name' in result['input_scenarios'][0]['input_payload']
    assert 'name' not in result['input_scenarios'][1]['input_payload']


def test_collection_probes_and_default_unchanged():
    result=generate_payload('<#list body.request.items as item>${item.name}</#list>')
    assert result['input_payload']['inputRequest']['items']==[{'name':'DEMO_name'}]
    probes=[s['input_payload']['inputRequest']['items'] for s in result['input_scenarios']]
    assert probes[0]==[]
    assert len(probes[1])==2


def test_unsupported_branch_reported_without_failing_payload():
    result=generate_payload('<#if body.name?matches("x")>yes<#else>no</#if>',direction='RESPONSE')
    assert result['input_payload']=={'name':'DEMO_name'}
    assert result['input_scenarios']==[]
    assert any('2 branches need manual test inputs' in w for w in result['warnings'])


def test_bound_and_no_branches():
    result=generate_payload('${body.name}',direction='RESPONSE')
    assert result['input_scenarios']==[]
    template=''.join('<#if body.status == "'+str(i)+'">x<#else>y</#if>' for i in range(30))
    result=generate_payload(template,direction='RESPONSE')
    assert len(result['input_scenarios'])<=20
    assert any('limit reached' in w for w in result['warnings'])


def test_compound_and_boolean_conditions():
    c=Condition('(body.status?? && body.status == "200") || body.active')
    assert c.evaluate(lambda ref: {'body.status':'200','body.active':False}[ref]) is True
    result=generate_payload('<#if body.active>yes<#else>no</#if>',direction='RESPONSE')
    assert [s['input_payload']['active'] for s in result['input_scenarios']]==[True,False]


def test_tools_api_exposes_additive_scenarios(client):
    response=client.post('/transformation-agent/api/v2/transformations/tools',json={
        'action':'generate_payload','type':'XMLTOJSON','direction':'RESPONSE','xml_root':'COMMAND',
        'template':'<#if body.STATUS == "200">ok<#else>failed</#if>'})
    assert response.status_code==200,response.text
    data=response.json()['data']
    assert isinstance(data['input_payload'],str)
    assert len(data['input_scenarios'])==2
    assert all(set(s)=={'name','input_payload'} for s in data['input_scenarios'])
    assert data['verified'] is False
    assert 'scenario_coverage' not in data
    assert all(isinstance(s['input_payload'],str) for s in data['input_scenarios'])


def test_regex_probes_and_xml_serialization():
    template=r'<#assign matches=body.MESSAGE?matches(r"\d+", "r")><#list matches as n>${n}</#list>'
    result=generate_payload(template,'XML','RESPONSE','COMMAND')
    values=[etree.fromstring(s['input_payload'].encode()).findtext('MESSAGE') for s in result['input_scenarios']]
    assert values[0]=='NO_MATCH'
    assert values[1].isdigit()
    assert len(values[2].split())==2


def test_contradictory_nested_branch_is_reported():
    result=generate_payload('<#if body.code == "A"><#if body.code == "B">x</#if></#if>',direction='RESPONSE')
    assert len(result['input_scenarios'])==1
    assert any('1 branches need manual test inputs' in w for w in result['warnings'])


def test_no_evaluation_of_custom_code():
    with pytest.raises(ValueError):Condition('__import__("os").system("anything")')
    with pytest.raises(ValueError):Condition('body.value == true').evaluate(lambda ref:1)
