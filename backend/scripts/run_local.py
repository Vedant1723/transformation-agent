"""Isolated local gateway-mode pilot. Never connects to the office database."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[2]
    private=root/'runtime-private'
    private.mkdir(exist_ok=True)
    config_file=private/'local-config.json'
    if not config_file.exists():
        with config_file.open('x',encoding='utf-8') as handle:
            json.dump({'gateway_key':secrets.token_urlsafe(48),'subject':'standalone_local','port':8020},handle)
    config=json.loads(config_file.read_text(encoding='utf-8'))
    os.environ.update(APP_ENV='production',AUTH_MODE='gateway',
        DATABASE_URL='sqlite:///'+str(private/'local.sqlite'),
        GATEWAY_SHARED_SECRET=config['gateway_key'],CORS_ORIGINS='http://127.0.0.1:8020')
    if args.check:
        import httpx
        base=f"http://127.0.0.1:{config['port']}/api/v2"
        headers={'X-Gateway-Key':config['gateway_key'],'X-Authenticated-User':config['subject']}
        with httpx.Client(timeout=20,headers=headers) as client:
            health=client.get(base+'/health');assert health.status_code==200,health.text
            context={'direction':'REQUEST','source':{'payload':{'inputRequest':{'amount':25},'headers':{},'additionalProperties':{}}},
                'target':{'payload':{'total':0}},'mappings':{'total':'amount'}}
            generated=client.post(base+'/transformations/generate',json=context)
            assert generated.status_code==200,generated.text
            template=generated.json()['data']['template']
            sample=client.post(base+'/transformations/tools',json={'action':'generate_payload','template':template})
            assert sample.status_code==200,sample.text
            rendered=client.post(base+'/transformations/test',json={'direction':'REQUEST','template':template,'input_payload':context['source']['payload']})
            report={'health':True,'generation':True,'payload_generator':True,'render_http_status':rendered.status_code,
                'render_passed':rendered.status_code==200 and rendered.json()['data']['passed'],
                'database':'isolated local SQLite; not PostgreSQL acceptance','interpreter':sys.executable}
            if report['render_passed']:
                assert json.loads(rendered.json()['data']['output'])=={'total':25}
                feedback=client.post(base+'/transformations/feedback',json={'context':context,'template':template,
                    'expected_output':'{"total":25}','approved':True,'sanitized':True})
                assert feedback.status_code==201,feedback.text
                report['reviewed_feedback']=feedback.json()['data']['dataset_eligible']
            else:
                report['render_blocker']='Java execution service unavailable or incompatible; configure JAVA_RUNTIME_URL.'
            report['model']=client.get(base+'/transformations/model').json()['data']
        (root/'sample-data'/'standalone-live-check.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2))
        return
    subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=root/'backend',check=True)
    subprocess.run([sys.executable,'-m','scripts.provision_gateway_user','--subject',config['subject'],
        '--email','standalone-local@example.invalid'],cwd=root/'backend',check=True)
    import uvicorn
    print('Local-only standalone API: http://127.0.0.1:8020/api/v2/docs',flush=True)
    print('Uses isolated SQLite. Gateway test credentials are in runtime-private/local-config.json; do not share that file.',flush=True)
    uvicorn.run('app.main:app',host='127.0.0.1',port=config['port'],access_log=False)


if __name__=='__main__':main()
