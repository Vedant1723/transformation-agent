import httpx
import pytest
from app.core.runtime_settings import RuntimeSettings
from app.transformations.runtime_client import FreeMarkerRuntimeClient


@pytest.mark.parametrize('env',[
    {'JAVA_RUNTIME_URL':'file:///tmp/service'},
    {'JAVA_RUNTIME_URL':'https://user:secret@example.test'},
    {'JAVA_RUNTIME_TRANSFORM_PATH':'//other.test'},
    {'JAVA_RUNTIME_TIMEOUT_SECONDS':'NaN'},
    {'JAVA_RUNTIME_TIMEOUT_SECONDS':'0'},
    {'JAVA_RUNTIME_TIMEOUT_SECONDS':'121'},
    {'JAVA_RUNTIME_BEARER_TOKEN':'bad\r\nheader'},
])
def test_invalid_configuration_rejected(env):
    with pytest.raises(ValueError):RuntimeSettings.from_environment(env)


def test_external_execution_and_health_share_settings(monkeypatch):
    settings=RuntimeSettings(base_url='https://java.example.test/service',transform_path='/execute',
        health_path='/status',timeout_seconds=7,bearer_token='secret-example')
    calls=[]
    def post(url,**kwargs):
        calls.append((url,kwargs))
        return httpx.Response(200,json={'success':True,'output':'{}'},request=httpx.Request('POST',url))
    def get(url,**kwargs):
        calls.append((url,kwargs))
        return httpx.Response(200,json={'status':'UP'},request=httpx.Request('GET',url))
    monkeypatch.setattr(httpx,'post',post);monkeypatch.setattr(httpx,'get',get)
    client=FreeMarkerRuntimeClient(settings=settings)
    assert client.execute('{}',{},'RESPONSE')['output']=='{}'
    assert client.health()['status']=='UP'
    assert calls[0][0]=='https://java.example.test/service/execute'
    assert calls[1][0]=='https://java.example.test/service/status'
    assert all(c[1]['headers']['Authorization']=='Bearer secret-example' for c in calls)
    assert calls[0][1]['timeout']==7 and calls[1][1]['timeout']==3
    assert 'secret-example' not in repr(settings)


@pytest.mark.parametrize('payload',[{},[],{'success':'true','output':'x'},{'success':True,'output':{}}])
def test_bad_upstream_contract_is_not_template_failure(monkeypatch,payload):
    monkeypatch.setattr(httpx,'post',lambda url,**kwargs:httpx.Response(200,json=payload,request=httpx.Request('POST',url)))
    with pytest.raises(httpx.HTTPStatusError) as error:
        FreeMarkerRuntimeClient(settings=RuntimeSettings()).execute('x',{})
    assert error.value.response.status_code==502


def test_factory_does_not_share_dependency_overrides(monkeypatch):
    from app.application import create_application
    monkeypatch.setenv('AUTH_MODE','gateway')
    first=create_application();second=create_application()
    assert first is not second
    assert first.state.integration_api.dependency_overrides is not second.state.integration_api.dependency_overrides
    assert not any(getattr(r,'path','').startswith('/api/v1') for r in first.routes)
