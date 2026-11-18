import pytest
from lxml import etree
from app.transformations.payload_generator import generate_payload
from test_generation_acceptance import client

TEMPLATE = r'''<#assign body = xml['child::node()']>{"txn_status": <#if body.TXNSTATUS?has_content>"$body.TXNSTATUS"<#else>null</#if>,<#if ((body.TXNSTATUS?has_content) && body.TXNSTATUS == "200")>"st": "true",<#else>"st": "false",</#if>"msgId": <#if body.TXNSTATUS?has_content>"$body.TXNSTATUS"<#else>null</#if>,"msg": <#if body.MESSAGE?has_content>"$body.MESSAGE"<#else>null</#if>,<#if ((body.TXNSTATUS?has_content) && body.TXNSTATUS == "200")><#assign numbers = body.MESSAGE?matches(r"\d+", "r")><#list numbers as msisdnNumber>"msisdn": "$msisdnNumber"</#list><#else>"msisdn": ""</#if>}'''


def test_reported_template_through_api(client):
    response=client.post('/transformation-agent/api/v2/transformations/tools',json={
        'action':'generate_payload','type':'XMLTOJSON','direction':'RESPONSE',
        'template':TEMPLATE,'xml_root':'COMMAND'})
    assert response.status_code == 200, response.text
    data=response.json()['data']
    root=etree.fromstring(data['input_payload'].encode())
    assert root.tag == 'COMMAND'
    assert root.findtext('TXNSTATUS') == '200'
    assert root.findtext('MESSAGE') == '256700000001'
    assert len(root.findall('MESSAGE')) == 1
    assert root.find('numbers') is None
    assert data['verified'] is False


@pytest.mark.parametrize('fmt', ['JSON','XML'])
@pytest.mark.parametrize('direction', ['REQUEST','RESPONSE'])
def test_regex_list_does_not_create_input_array(fmt,direction):
    prefix='body.request' if direction=='REQUEST' else 'body'
    template=r'<#assign numbers = PREFIX.message?matches(r"\d+", "r")><#list numbers as n>${n}</#list>'.replace('PREFIX',prefix)
    result=generate_payload(template,fmt,direction)['input_payload']
    if direction=='REQUEST':result=result['inputRequest']
    if fmt=='JSON':assert result == {'message':'256700000001'}
    else:assert etree.fromstring(result.encode()).findtext('message') == '256700000001'


def test_unknown_regex_keeps_warning_and_scalar():
    result=generate_payload('<#assign codes=body.message?matches("[A-Z]{3}")><#list codes as c>${c}</#list>',direction='RESPONSE')
    assert isinstance(result['input_payload']['message'],str)
    assert any('review the sample' in w for w in result['warnings'])


def test_reassigned_alias_is_not_incorrectly_inferred():
    with pytest.raises(ValueError):
        generate_payload('<#assign x=body.message?matches("x")><#assign x=helper()><#list x as n>${n}</#list>')
