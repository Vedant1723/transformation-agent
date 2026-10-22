"""Bounded inference using the copied checkpoint; never trains or promotes it."""
import argparse
import hashlib
import json
import sys
from app.transformations.local_model import ROOT, RUN, CHECKPOINT, status, validate_input, _invoke_worker


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--amount',type=json.loads,default=25)
    parser.add_argument('--target',default='value')
    parser.add_argument('--format',choices=['JSON','XML'],default='JSON')
    args=parser.parse_args()
    if not status()['available']:raise SystemExit('Install requirements-training.txt and check registered model artifacts.')
    source={'amount':args.amount}
    validate_input(source,args.target,args.format)
    checkpoint=ROOT/'model-runs'/RUN/CHECKPOINT
    before=hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    result=json.loads(_invoke_worker(json.dumps({'source':source,'target_field':args.target,'target_format':args.format})))
    assert hashlib.sha256(checkpoint.read_bytes()).hexdigest()==before,'Checkpoint changed unexpectedly.'
    report={'inference_completed':True,'active_checkpoint_unchanged':True,'python':sys.executable,'result':result}
    path=ROOT/'sample-data'/('model-inference-'+args.format.lower()+'.json')
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'inference_completed':True,'checkpoint_unchanged':True,'template_generated':bool(result['template']),
        'render_passed':result['render_passed'],'mapping_passed':result['mapping_passed'],
        'java_service_unavailable':result['infrastructure_error'],'report':str(path)},indent=2))


if __name__=='__main__':main()
