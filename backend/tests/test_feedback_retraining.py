from types import SimpleNamespace
from unittest.mock import Mock
from app.services.feedback_retraining import schedule


def test_disabled_does_not_touch_database(monkeypatch):
    monkeypatch.delenv('FEEDBACK_AUTO_TRAIN', raising=False)
    db = Mock()
    assert schedule(SimpleNamespace(id=1), db)['status'] == 'disabled'
    assert not db.mock_calls


def test_nonoperator_cannot_start_training(monkeypatch):
    monkeypatch.setenv('FEEDBACK_AUTO_TRAIN', 'true')
    monkeypatch.setenv('TRAINING_OPERATOR_IDS', '2')
    db = Mock()
    assert schedule(SimpleNamespace(id=1), db)['status'] == 'operator_not_enabled'
    assert not db.mock_calls
