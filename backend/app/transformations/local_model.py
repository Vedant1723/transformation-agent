"""Explicit experimental checkpoint; no automatic promotion or rule fallback."""
from app.core.observability import traced as _log_traced, exception_event as _log_exception
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading

ROOT=Path(__file__).resolve().parents[3]
RUN='expanded-resume-20260921-114948'
CHECKPOINT='checkpoint.pt'
XML_TARGETS=('value','total','totalAmount','result')
TARGETS=('value','result','data','mappedValue','total','totalAmount','charge','chargeAmount',
         'paidAmount','balance','grossAmount','netAmount','fee','tax','paymentAmount',
         'settledAmount','requestedAmount','debitAmount','creditAmount','transferAmount')
_busy=threading.Lock()


@_log_traced('app.transformations.local_model._invoke_worker', level=10)
def _invoke_worker(payload):
    from app.core.observability import child_environment
    env={**child_environment(),'CUDA_VISIBLE_DEVICES':'-1'}
    process=subprocess.Popen([sys.executable,'-m','scripts.local_model_worker'],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=None,text=True,
        cwd=ROOT/'backend',env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        stdout,stderr=process.communicate(payload,timeout=120)
    except subprocess.TimeoutExpired:
        # A Windows virtualenv launcher can have a child interpreter. Stop that
        # worker tree, not just the launcher, without touching other Python jobs.
        _log_exception('app.transformations.local_model:29', handled=True)
        try:
            if os.name=='nt':
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=10,
                               creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        finally:
            if process.poll() is None:process.kill()
            process.communicate(timeout=10)
        raise
    if process.returncode:raise RuntimeError('Local model worker failed. Check the installed Python/PyTorch and checkpoint files.')
    return stdout


@_log_traced('app.transformations.local_model.validate_input', level=10)
def validate_input(source, target, target_format='JSON'):
    if not isinstance(source,dict) or set(source)!={'amount'}:
        raise ValueError('Experimental scope: JSON source containing only a numeric amount.')
    amount=source['amount']
    if type(amount) not in (int,float) or abs(amount)>1_000_000_000 or not math.isfinite(amount):
        raise ValueError('Amount must be a finite number between -1000000000 and 1000000000.')
    if target_format not in ('JSON','XML'):raise ValueError('Experimental output must be JSON or XML.')
    if target not in (XML_TARGETS if target_format=='XML' else TARGETS):raise ValueError('Choose one of the experimental target fields for this format.')


@_log_traced('app.transformations.local_model.status', level=10)
def status():
    return {'available':all((ROOT/'model-runs'/RUN/name).is_file() for name in (CHECKPOINT,'bundle.json')) and importlib.util.find_spec('torch') is not None,
            'checkpoint':RUN+'/'+CHECKPOINT,'targets':list(TARGETS),'formats':{'JSON':list(TARGETS),'XML':list(XML_TARGETS)},
            'scope':'REQUEST JSON → JSON or XML, one numeric amount field only. XML uses a Payment root and four supported elements.',
            'warning':'Experimental own model. Learned-schema tests are not general accuracy. Every output requires execution, exact mapping checks and human review. No rule-based fallback.'}


@_log_traced('app.transformations.local_model.generate_checked', level=10)
def generate_checked(source, target, target_format='JSON'):
    validate_input(source,target,target_format)
    if not _busy.acquire(blocking=False):raise BlockingIOError('A local model request is already running. Retry after it finishes.')
    try:
        result=json.loads(_invoke_worker(json.dumps({'source':source,'target_field':target,'target_format':target_format})))
        if result.get('infrastructure_error'):raise RuntimeError('FreeMarker service unavailable. Start the Java service on port 8090.')
        if not isinstance(result.get('passed'),bool):raise RuntimeError('Invalid local model response.')
        return result
    finally:
        _busy.release()


@_log_traced('app.transformations.local_model.worker', level=10)
def worker(source,target,target_format='JSON',guided=None):
    # Called only in a bounded child process, never load torch into the API server.
    import torch
    from app.transformations.tiny_model import TinyTransformer, generate_template
    from app.transformations.training_bundle import pair
    from app.transformations.dataset import digest
    from app.transformations.scoring import score_case
    if guided is None:validate_input(source,target,target_format)
    else:
        from app.transformations.guided_model import validate
        validate(source,target,guided['kind'],guided.get('selected_source'),target_format)
    run=ROOT/'model-runs'/RUN
    checkpoint=run/CHECKPOINT
    if checkpoint.stat().st_size>100_000_000:raise ValueError('Unexpected checkpoint size.')
    saved=torch.load(checkpoint,map_location='cpu',weights_only=True)
    bundle=json.loads((run/'bundle.json').read_text(encoding='utf-8'))
    if digest({k:v for k,v in bundle.items() if k!='content_sha256'})!=saved['bundle_sha256'] or saved['tokenizer']!=bundle['tokenizer']:
        raise ValueError('Checkpoint/tokenizer integrity failed.')
    torch.set_num_threads(2)
    model=TinyTransformer(**saved['config']);model.load_state_dict(saved['model'],strict=True);model.eval()
    if guided is not None:
        from app.transformations.guided_model import run as guided_run
        return {**guided_run(model,saved['tokenizer'],source,target,guided['kind'],guided.get('selected_source'),target_format),
                'checkpoint':RUN+'/'+CHECKPOINT,'checkpoint_sha256':hashlib.sha256(checkpoint.read_bytes()).hexdigest()}
    context={'direction':'REQUEST','source':{'format':'JSON','payload':source},
             'target':{'format':'JSON','payload':{target:0}},'mappings':{target:'amount'},'validations':[]}
    expected=json.dumps({target:source['amount']})
    if target_format=='XML':
        context['target']={'format':'XML','payload':f'<Payment><{target}/></Payment>'}
        context['mappings']={f'Payment.{target}':'amount'}
        expected=f"<Payment><{target}>{source['amount']}</{target}></Payment>"
    record={'id':'local-model-preview','split':'evaluation','provenance':{},
            'example':{'context':context,'template':'','test':{'passed':True,'output':expected}}}
    prediction=generate_template(model,pair(record)['prompt'],saved['tokenizer'],'cpu',max_new_tokens=850)
    record['example']['template']=prediction['template']
    execution=score_case(record,'replay')
    return {**execution_checks(execution, prediction['ended']),
            'infrastructure_error':execution['status']=='infrastructure_error',
            'engine':'own-model-experimental','checkpoint':RUN+'/'+CHECKPOINT,
            'checkpoint_sha256':hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            'template':prediction['template'],'output':execution['actual'],
            'expected':execution['expected'],'error':execution['error'] or ('Output does not match the requested field and value.' if execution['status']=='mismatch' else '' if prediction['ended'] else prediction['reason']),
            'stage':execution['stage'],'source':source,'target_field':target,'target_format':target_format,
            'approved':False,'fallback_used':False}


@_log_traced('app.transformations.local_model.execution_checks', level=10)
def execution_checks(execution, ended=True):
    """A valid output may still contain the wrong business mapping."""
    render_passed=bool(ended and execution['status'] in ('passed','mismatch'))
    mapping_passed=bool(ended and execution['status']=='passed')
    return {'passed':mapping_passed,'render_passed':render_passed,
            'mapping_passed':mapping_passed,
            'mapping_warning':'Rendered successfully, but the requested field or value differs. Correct the mapping before business use.' if render_passed and not mapping_passed else ''}
