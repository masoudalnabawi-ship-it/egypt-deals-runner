"""Fail-closed Cloudflare D1 admission client. Does not run automatically."""
import json
import os
import urllib.request

def claim_run(opener=None):
    url=os.environ.get('V16_WORKER_URL','').rstrip('/')
    secret=os.environ.get('V16_REGISTRATION_SECRET','')
    if not url.startswith('https://') or not secret:
        raise RuntimeError('V16_CLOUD_BUDGET_NOT_CONFIGURED')
    req=urllib.request.Request(url+'/budget/claim',data=b'{}',method='POST',headers={'Authorization':'Bearer '+secret,'Content-Type':'application/json'})
    with (opener or urllib.request.urlopen)(req,timeout=12) as r:
        data=json.load(r)
    if type(data.get('allowed')) is not bool:
        raise RuntimeError('V16_CLOUD_BUDGET_INVALID_RESPONSE')
    return data['allowed']
