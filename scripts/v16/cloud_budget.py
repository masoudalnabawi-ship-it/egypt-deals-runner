"""Fail-closed Cloudflare D1 admission client. Does not run automatically."""
import json
import os
import urllib.request
import subprocess

def claim_run(opener=None):
    url=os.environ.get('V16_WORKER_URL','').rstrip('/')
    secret=os.environ.get('V16_REGISTRATION_SECRET','')
    if not url.startswith('https://') or not secret:
        raise RuntimeError('V16_CLOUD_BUDGET_NOT_CONFIGURED')
    req=urllib.request.Request(url+'/budget/claim',data=b'{}',method='POST',headers={'Authorization':'Bearer '+secret,'Content-Type':'application/json'})
    if opener is not None:
        with opener(req, timeout=12) as r:
            data=json.load(r)
    else:
        result=subprocess.run(
            ['curl','--fail-with-body','--silent','--show-error',
             '--max-time','12','--request','POST',
             '--header','Authorization: Bearer '+secret,
             '--header','Content-Type: application/json',
             '--data-binary','{}',
             url+'/budget/claim'],
            capture_output=True,text=True,timeout=15,check=True
        )
        data=json.loads(result.stdout)
    if type(data.get('allowed')) is not bool:
        raise RuntimeError('V16_CLOUD_BUDGET_INVALID_RESPONSE')
    return data['allowed']
