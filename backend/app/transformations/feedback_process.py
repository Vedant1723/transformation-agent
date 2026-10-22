"""Bounded, isolated feedback training process. No shell or user-selected executable."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import json
import os
from pathlib import Path
import subprocess
import sys
from app.transformations.windows_job import WindowsJob


class CleanupUncertain(RuntimeError):
    pass


@_log_traced('app.transformations.feedback_process.stop_owned_process', level=10)
def stop_owned_process(process):
    if process.poll() is not None:return
    if os.name=='nt':
        result=subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,
            timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode and process.poll() is None:
            raise CleanupUncertain('Worker process tree termination could not be confirmed.')
    else:process.kill()
    try:process.communicate(timeout=15)
    except subprocess.TimeoutExpired as exc:_log_exception('app.transformations.feedback_process:23', handled=True); raise CleanupUncertain('Worker termination timed out.') from exc


@_log_traced('app.transformations.feedback_process.bounded_train', level=10)
def bounded_train(bundle,manifest,steps,job_id):
    payload=json.dumps({'bundle':bundle,'manifest':manifest,'steps':steps,'job_id':job_id})
    if len(payload.encode())>4_000_000:raise ValueError('Worker payload exceeds limit.')
    from app.core.observability import child_environment
    process=subprocess.Popen([sys.executable,'-m','scripts.feedback_train_child'],
        cwd=Path(__file__).resolve().parents[2],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
        stderr=None,text=True,env=child_environment(),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    containment=None
    try:
        containment=WindowsJob(process)
        stdout,_=process.communicate(payload,timeout=600)
    except BaseException:
        _log_exception('app.transformations.feedback_process:36', handled=True)
        try:stop_owned_process(process)
        except Exception as exc:_log_exception('app.transformations.feedback_process:38', handled=True); raise CleanupUncertain('Worker cleanup requires operator verification.') from exc
        raise
    finally:
        if containment is not None:containment.close()
    if process.returncode:raise RuntimeError('Feedback training subprocess failed.')
    result=json.loads(stdout)
    if not isinstance(result,dict) or result.get('promoted') is not False:raise ValueError('Unexpected worker result.')
    return result
