import pytest
from test_generation_acceptance import client

BASE='/transformation-agent/api/v2/transformations/generate'


@pytest.mark.parametrize('direction',['REQUEST','RESPONSE'])
@pytest.mark.parametrize('sf',['JSON','XML','ISO'])
@pytest.mark.parametrize('tf',['JSON','XML','ISO'])
def test_all_format_pairs(client,direction,sf,tf):
    sources={'JSON':{'status':'200'},'XML':'<Reply><status>200</status></Reply>','ISO':'39=200'}
    targets={'JSON':{'message':''},'XML':'<Result><message/></Result>','ISO':'48='}
    field={'JSON':'status','XML':'Reply.status','ISO':'39'}[sf]
    target={'JSON':'message','XML':'Result.message','ISO':'48'}[tf]
    conditions=[{'target':target,'branches':[
        {'field':field,'operator':'eq','value':'200','then':'Success'},
        {'field':field,'operator':'eq','value':'400','then':'Invalid'}], 'else':'Failed'}]
    result=client.post(BASE,json={'direction':direction,'type':sf+'TO'+tf,'source':sources[sf],'target':targets[tf],'conditions':conditions})
    assert result.status_code==200,result.text
    data=result.json()['data'];template=data['template']
    assert '<#elseif ' in template and '<#else>' in template
    assert 'Success' in template and 'Invalid' in template and 'Failed' in template
    assert data['conditions']==conditions
    assert data['mappings'][0]['reason']=='Explicit business conditions'


@pytest.mark.parametrize('rule',[
    {'target':'unknown','branches':[{'field':'status','operator':'eq','value':'200','then':'ok'}],'else':'bad'},
    {'target':'message','branches':[{'field':'missing','operator':'eq','value':'200','then':'ok'}],'else':'bad'},
    {'target':'message','branches':[{'field':'status','operator':'raw','value':'200','then':'ok'}],'else':'bad'},
    {'target':'message','branches':[{'field':'status','operator':'eq','value':'200','then':{}}],'else':'bad'},
    {'target':'message','branches':[],'else':'bad'},
    {'target':'message','branches':[{'field':'status','operator':'gt','value':'200','then':'ok'}],'else':'bad'},
])
def test_invalid_rules_rejected(client,rule):
    result=client.post(BASE,json={'direction':'RESPONSE','type':'JSONTOJSON','source':{'status':'200'},'target':{'message':''},'conditions':[rule]})
    assert result.status_code==422,result.text


def test_numeric_boolean_and_missing_rules(client):
    result=client.post(BASE,json={'direction':'REQUEST','source':{'amount':10,'active':True},
        'target':{'fee':0,'enabled':False},'conditions':[
            {'target':'fee','branches':[{'field':'amount','operator':'gte','value':10,'then':2}],'else':0},
            {'target':'enabled','branches':[{'field':'active','operator':'exists','then':True}],'else':False}]})
    assert result.status_code==200,result.text
    assert '?number gte 10' in result.json()['data']['template']


def test_list_conditions_are_scoped(client):
    result=client.post(BASE,json={'direction':'REQUEST','source':{'items':[{'status':'200'}]},
        'target':{'items':[{'message':''}]},'conditions':[
            {'target':'items.0.message','branches':[{'field':'items.0.status','operator':'eq','value':'200','then':'OK'}],'else':'FAILED'}]})
    assert result.status_code==200,result.text
    template=result.json()['data']['template']
    assert '<#list ' in template
    assert 'body.request.items[0].status' not in template
