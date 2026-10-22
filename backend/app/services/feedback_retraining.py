"""Automatic scheduling over the existing reviewed-data training pipeline."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import os
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from fastapi import HTTPException
from app.transformations.conversation_models import TransformationTrainingJob as Job
from app.transformations.dataset import digest
from app.services import transformation_datasets as datasets
from app.services import transformation_training as training
from app.services import transformation_jobs as jobs


@_log_traced('app.services.feedback_retraining.schedule', level=20)
def schedule(user, db):
    if os.getenv('FEEDBACK_AUTO_TRAIN', 'false').lower() != 'true':
        return {'status': 'disabled', 'active_model_changed': False}
    try:
        jobs.operator(user)
    except HTTPException:
        _log_exception('app.services.feedback_retraining:18', handled=True)
        return {'status': 'operator_not_enabled', 'active_model_changed': False}
    # Serialize scheduling per owner on PostgreSQL. Existing request-key uniqueness
    # remains authoritative on SQLite and under concurrent requests.
    state = datasets.policy(db, user, lock=True)
    seeds = datasets.benchmark(db, user, state)
    if not seeds:
        db.rollback()
        return {'status': 'waiting_for_benchmark', 'active_model_changed': False}
    pending = db.scalar(select(Job).where(Job.user_id == user.id,
        Job.status.in_(['queued', 'running', 'cleanup_required'])).order_by(Job.id))
    if pending:
        db.rollback()
        return {'status': pending.status, 'job_id': pending.id, 'active_model_changed': False}
    candidates = datasets.list_candidates(user, db)['data']
    eligible = sorted((r for r in candidates if r['eligible']), key=lambda r: (r['session_id'], r['revision']), reverse=True)
    capacity = 20 - len(seeds)
    if capacity < 1:
        db.rollback()
        return {'status': 'benchmark_too_large', 'active_model_changed': False}
    selected = eligible[:capacity]
    if not selected:
        db.rollback()
        return {'status': 'waiting_for_eligible_feedback', 'active_model_changed': False}
    fingerprints = {row['key']: row['fingerprint'] for row in selected}
    steps = int(os.getenv('FEEDBACK_TRAIN_STEPS', '50'))
    if not 1 <= steps <= 500:
        raise ValueError('FEEDBACK_TRAIN_STEPS must be between 1 and 500.')
    key = 'auto-' + digest({'fingerprints': fingerprints, 'benchmark': state['benchmark_id'],
                          'training_policy': 'feedback-replay-v2', 'steps': steps})
    previous = db.scalar(select(Job).where(Job.user_id == user.id, Job.request_key == key))
    if previous:
        db.rollback()
        return {'status': previous.status, 'job_id': previous.id, 'active_model_changed': False}
    exported = datasets.export(datasets.ExportSelection(fingerprints=fingerprints, human_reviewed=True), user, db)['data']
    prepared = training.prepare_existing(training.PrepareExisting(dataset_id=exported['id']), user, db)['data']
    job = jobs.enqueue(jobs.Queue(bundle_id=prepared['id'], request_key=key, steps=steps), user, db)['data']
    return {'status': job['status'], 'job_id': job['id'], 'active_model_changed': False}


@_log_traced('app.services.feedback_retraining.schedule_safely', level=20)
def schedule_safely(user, db):
    try:
        return schedule(user, db)
    except (HTTPException, ValueError, OSError, SQLAlchemyError):
        _log_exception('app.services.feedback_retraining:61', handled=True)
        db.rollback()
        return {'status': 'preparation_blocked', 'active_model_changed': False,
                'message': 'Feedback is saved. Check benchmark, data eligibility and model preparation.'}


@_log_traced('app.services.feedback_retraining.status', level=20)
def status(user, db):
    row = db.scalar(select(Job).where(Job.user_id == user.id).order_by(Job.id.desc()))
    return {'enabled': os.getenv('FEEDBACK_AUTO_TRAIN', 'false').lower() == 'true',
            'latest_job': jobs.view(row) if row else None,
            'activation': 'not_implemented_candidates_only'}
