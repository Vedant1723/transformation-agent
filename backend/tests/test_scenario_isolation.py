import pytest
from app.transformations.payload_generator import generate_payload
from test_generation_acceptance import client

MODULE='app.transformations.payload_generator.build_scenarios'


@pytest.mark.parametrize('fmt',['JSON','XML','ISO'])
@pytest.mark.parametrize('direction',['REQUEST','RESPONSE'])
def test_scenario_mutation_and_failure_preserves_default(monkeypatch,fmt,direction):
    prefix='body.request' if direction=='REQUEST' else 'body'
    ref=prefix+'["4"]' if fmt=='ISO' else prefix+'.amount'
    template='${'+ref+'?number}'
    if direction=='REQUEST':template+=' ${body.headers.trace} ${body.addProps.region}'
    expected=generate_payload(template,fmt,direction)['input_payload']
    def broken(template,data,headers,props,*args):
        data.clear();headers.clear();props.clear()
        raise RuntimeError('Sensitive exception detail must not be returned')
    monkeypatch.setattr(MODULE,broken)
    result=generate_payload(template,fmt,direction)
    assert result['input_payload']==expected
    assert result['input_scenarios']==[]
    assert any('default input_payload is available and unchanged' in w for w in result['warnings'])
    assert 'Sensitive exception' not in str(result)


def test_malformed_scenario_output_is_optional(monkeypatch):
    monkeypatch.setattr(MODULE,lambda *args:([{'broken':True}],{}))
    result=generate_payload('${body.request.amount?number}')
    assert result['input_payload']['inputRequest']=={'amount':10}
    assert result['input_scenarios']==[]


def test_api_stays_successful_when_scenarios_fail(client,monkeypatch):
    def broken(*args):raise ValueError('Scenario failure')
    monkeypatch.setattr(MODULE,broken)
    response=client.post('/transformation-agent/api/v2/transformations/tools',json={
        'action':'generate_payload','direction':'RESPONSE','type':'XMLTOJSON','xml_root':'COMMAND',
        'template':'${body.amount?number}'})
    assert response.status_code==200,response.text
    assert response.json()['st'] is True
    assert '<amount>10</amount>' in response.json()['data']['input_payload']
    assert response.json()['data']['input_scenarios']==[]


def test_default_generation_error_is_not_swallowed(monkeypatch):
    def should_not_run(*args):raise AssertionError('Scenarios must not run for invalid default')
    monkeypatch.setattr(MODULE,should_not_run)
    with pytest.raises(ValueError,match='XML root'):
        generate_payload('${body.name}', 'XML','RESPONSE','invalid root')
