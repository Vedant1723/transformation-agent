import json
import pytest
from test_generation_acceptance import client

BASE='/transformation-agent/api/v2/transformations/'
PAYLOADS={'JSON':{'amount':25},'XML':'<Payment><amount>25</amount></Payment>','ISO':'4=25'}


@pytest.mark.parametrize('direction',['REQUEST','RESPONSE'])
@pytest.mark.parametrize('source_format',PAYLOADS)
@pytest.mark.parametrize('target_format',PAYLOADS)
def test_discovered_paths_work_in_generate(client,direction,source_format,target_format):
    request={'direction':direction,'type':source_format+'TO'+target_format,
             'source':PAYLOADS[source_format],'target':PAYLOADS[target_format]}
    response=client.post(BASE+'mapping-fields',json=request)
    assert response.status_code==200,response.text
    data=response.json()['data']
    source=data['sourcePayloadKeys'][-1]
    target=data['targetPayloadKeys'][-1]
    assert all(isinstance(path,str) for path in data['sourcePayloadKeys']+data['targetPayloadKeys'])
    response=client.post(BASE+'generate',json={**request,'mappings':{target:source},
        'validations':[{'field':source,'type':'min','value':1}]})
    assert response.status_code==200,response.text
    assert response.json()['data']['mappings'][0]['source_field']==source


def test_hierarchy_strings_and_metadata(client):
    response=client.post(BASE+'mapping-fields',json={'direction':'REQUEST','type':'JSONTOJSON',
        'source':{'inputRequest':json.dumps({'customer':{'name':'Alice'},'items':[{'sku':'A'},{'sku':'B'}]}),
                  'inputHeaders':{'x-channel-name':'WEB'},'additionalProperties':{'region':'UG'}},
        'target':{'fullName':'','orders':[{'code':''}]}})
    assert response.status_code==200,response.text
    data=response.json()['data']
    assert data['sourcePayloadKeys']==['customer.name','items.0.sku','items.1.sku','headers.x-channel-name','addProps.region']
    assert data['targetPayloadKeys']==['fullName','orders.0.code']
    assert {v['type'] for v in data['validations']}=={'required','min','max','length','min_length','max_length','regex','email','enum','type'}
    assert 'Alice' not in response.text


def test_xml_attributes_and_empty_arrays_are_explicit(client):
    response=client.post(BASE+'mapping-fields',json={'direction':'RESPONSE','type':'XMLTOJSON',
        'source':'<Payment id="123"><items><item><code>A</code></item><item><code>B</code></item></items></Payment>',
        'target':{'items':[]}})
    assert response.status_code==200,response.text
    data=response.json()['data']
    assert data['sourcePayloadKeys']==['Payment.items.item.0.code','Payment.items.item.1.code']
    assert data['targetPayloadKeys']==[]
    assert data['warnings']


def test_dotted_collision_reported(client):
    response=client.post(BASE+'mapping-fields',json={'direction':'RESPONSE',
        'source':{'a.b':1,'a':{'b':2}},'target':{'x':0}})
    assert response.status_code==200,response.text
    assert response.json()['data']['sourcePayloadKeys']==[]
    assert any('ambiguous' in w for w in response.json()['data']['warnings'])


@pytest.mark.parametrize('source,type_', [('<broken>','XMLTOJSON'),('129=x','ISOTOJSON'),('{bad','JSONTOJSON')])
def test_bad_payloads_return_422(client,source,type_):
    response=client.post(BASE+'mapping-fields',json={'direction':'RESPONSE','type':type_,'source':source,'target':{'x':0}})
    assert response.status_code==422,response.text


def test_deep_payload_is_bounded(client):
    source={'value':1}
    for _ in range(22):source={'nested':source}
    response=client.post(BASE+'mapping-fields',json={'direction':'RESPONSE','source':source,'target':{'value':0}})
    assert response.status_code==422,response.text
