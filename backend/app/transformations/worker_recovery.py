"""Fail-closed recovery for contained local Windows workers, never legacy jobs."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import os
import socket
from sqlalchemy import update
from app.transformations.conversation_models import TransformationTrainingJob
from app.transformations.windows_job import process_identity


@_log_traced('app.transformations.worker_recovery.ownership', level=10)
def ownership():
    if os.name!='nt':return {}
    return {'protocol':'windows-contained-v1','host':socket.gethostname(),
            'pid':os.getpid(),'created':process_identity(os.getpid())}


@_log_traced('app.transformations.worker_recovery.recover_dead_worker', level=10)
def recover_dead_worker(db,job_id):
    job=db.get(TransformationTrainingJob,job_id)
    if not job or job.status!='running' or job.running_slot!=1:return False
    owner=(job.result or {}).get('worker',{})
    if os.name!='nt' or owner.get('protocol')!='windows-contained-v1' or owner.get('host')!=socket.gethostname():return False
    if not isinstance(owner.get('pid'),int) or not isinstance(owner.get('created'),int):return False
    try:
        if process_identity(owner['pid'])==owner['created']:return False
    except OSError:_log_exception('app.transformations.worker_recovery:23', handled=True); return False
    # This protocol guarantees no training input before containment and kills
    # the child tree on parent exit. Legacy/foreign jobs are never auto-released.
    changed=db.execute(update(TransformationTrainingJob).where(
        TransformationTrainingJob.id==job_id,TransformationTrainingJob.status=='running',
        TransformationTrainingJob.running_slot==1).values(status='failed',running_slot=None,
        result={'error':'Contained worker exited unexpectedly; active model unchanged.',
                'recovery':'dead_local_parent','worker':owner}))
    db.commit()
    return changed.rowcount==1
