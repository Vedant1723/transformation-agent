import pytest
from app.transformations.template_corrections import correct_bare_references
from test_generation_acceptance import client


def test_scoped_aliases_and_preserved_code():
    original='<#assign text="$body.name"><#-- $body.name --><#noparse>$body.name</#noparse>${body.name} \\$body.name $unknown <#list body.items as item>"$item" "$item.name"</#list> $item "$body.name"'
    fixed, changes=correct_bare_references(original)
    assert len(changes)==3
    assert '<#assign text="$body.name">' in fixed
    assert '<#noparse>$body.name</#noparse>' in fixed
    assert '"${item}" "${item.name}"' in fixed
    assert '</#list> $item "${body.name}"' in fixed
    assert correct_bare_references(fixed)==(fixed,[])
    assert correct_bare_references('<#list body.items as item>$itemOther</#list>')[1] == []


@pytest.mark.parametrize('direction', ['REQUEST','RESPONSE'])
def test_payload_reports_corrections(client,direction):
    ref='body.request.name' if direction=='REQUEST' else 'body.name'
    response=client.post('/transformation-agent/api/v2/transformations/tools',json={
        'action':'generate_payload','type':'XMLTOJSON','direction':direction,
        'template':'{"name":"$'+ref+'"}'})
    assert response.status_code==200,response.text
    data=response.json()['data']
    assert data['corrected_template']=='{"name":"${'+ref+'}"}'
    assert len(data['corrections'])==1
    assert data['verified'] is False


@pytest.mark.parametrize('direction', ['REQUEST','RESPONSE'])
def test_corrected_template_sent_to_runtime(client,monkeypatch,direction):
    ref='body.request.name' if direction=='REQUEST' else 'body.name'
    def execute(self,template,*args,**kwargs):
        assert template=='{"name":"${'+ref+'}"}'
        return {'success':True,'output':'{"name":"Alice"}'}
    monkeypatch.setattr('app.services.transformations.FreeMarkerRuntimeClient.execute',execute)
    response=client.post('/transformation-agent/api/v2/transformations/test',json={
        'direction':direction,'source_format':'JSON','target_format':'JSON',
        'input_payload':{'name':'Alice'},'template':'{"name":"$'+ref+'"}'})
    assert response.status_code==200,response.text
    assert response.json()['data']['passed'] is True
    assert response.json()['data']['corrections']


def test_failed_runtime_still_returns_diagnostics(client,monkeypatch):
    monkeypatch.setattr('app.services.transformations.FreeMarkerRuntimeClient.execute',lambda *a,**k: {'success':False,'error':'Missing field'})
    response=client.post('/transformation-agent/api/v2/transformations/test',json={
        'direction':'RESPONSE','input_payload':{'name':'Alice'},'template':'{"name":"$body.name"}'})
    assert response.status_code==200,response.text
    assert response.json()['data']['passed'] is False
    assert response.json()['data']['corrected_template']=='{"name":"${body.name}"}'
