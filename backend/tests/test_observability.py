import io
import json
import logging
import pytest
from fastapi.testclient import TestClient
from app.core import observability as obs
from app.main import app


@pytest.fixture
def logs(monkeypatch):
    monkeypatch.setenv('LOG_LEVEL', 'DEBUG')
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(obs.JsonFormatter())
    previous = list(obs.logger.handlers)
    level = obs.logger.level
    obs.logger.handlers = [handler]
    obs.configure_logging()
    try:
        yield stream
    finally:
        obs.logger.handlers = previous
        obs.logger.setLevel(level)


def test_method_logging_redacts_arguments_results_and_exception_text(logs):
    @obs.traced('synthetic.method')
    def method(payload):
        raise ValueError(payload)
    with pytest.raises(ValueError):
        method('private-token-123')
    text = logs.getvalue()
    assert 'private-token-123' not in text
    rows = [json.loads(line) for line in text.splitlines()]
    assert rows[-1]['exception_type'] == 'ValueError'
    assert rows[-1]['frames']
    assert rows[0]['event'] == 'operation.started'


def test_request_id_and_query_redaction(logs):
    client = TestClient(app)
    response = client.get('/health?password=private-token-123', headers={'Authorization': 'Bearer private-token-123'})
    assert response.status_code == 200
    request_id = response.headers['X-Request-ID']
    assert len(request_id) == 32
    rows = [json.loads(line) for line in logs.getvalue().splitlines()]
    assert any(row['event'] == 'request.completed' and row['correlation_id'] == request_id for row in rows)
    assert 'private-token-123' not in logs.getvalue()
    assert not obs.correlation_id.get()


def test_unknown_path_not_logged(logs):
    response = TestClient(app).get('/private-token-123')
    assert response.status_code == 404
    assert 'private-token-123' not in logs.getvalue()


def test_job_correlation_and_child_context(logs):
    @obs.traced('synthetic.job', level=logging.INFO)
    def job(job_id):
        assert obs.child_environment()['TRANSFORMATION_TRACE_ID'] == 'job-23'
        return {'passed': True}
    assert job(23) == {'passed': True}
    rows = [json.loads(line) for line in logs.getvalue().splitlines()]
    assert any(row.get('job_id') == 23 and row['correlation_id'] == 'job-23' for row in rows)
    assert not obs.correlation_id.get()


def test_debug_can_be_suppressed(logs, monkeypatch):
    monkeypatch.setenv('LOG_LEVEL', 'INFO')
    @obs.traced('synthetic.debug')
    def method():
        return {'secret': 'private-token-123'}
    assert method()['secret'] == 'private-token-123'
    assert logs.getvalue() == ''


def test_handled_exception_does_not_include_message(logs):
    try:
        raise RuntimeError('private-token-123')
    except RuntimeError:
        obs.exception_event('synthetic.handler', handled=True)
    assert 'exception.handled' in logs.getvalue()
    assert 'private-token-123' not in logs.getvalue()
