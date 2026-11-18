import pytest
from test_generation_acceptance import client


@pytest.mark.parametrize('extra', [{}, {'mappings':None}, {'mappings':''}, {'mappings':[]}, {'mappings':{}}])
def test_empty_mappings_use_automatic_suggestions(client, extra):
    response = client.post('/transformation-agent/api/v2/transformations/generate', json={
        'direction':'REQUEST','type':'JSONTOJSON',
        'source':{'name':'Alice'}, 'target':{'fullName':''}, **extra})
    assert response.status_code == 200, response.text
    assert response.json()['data']['mappings'][0]['source_field'] == 'name'


@pytest.mark.parametrize('value', ['name', ['name'], 1, False])
def test_nonempty_invalid_mapping_rejected(client, value):
    response = client.post('/transformation-agent/api/v2/transformations/generate', json={
        'direction':'REQUEST','type':'JSONTOJSON','source':{'name':'Alice'},
        'target':{'fullName':''}, 'mappings':value})
    assert response.status_code == 422
