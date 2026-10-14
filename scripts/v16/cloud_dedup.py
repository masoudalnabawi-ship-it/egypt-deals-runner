"""Persistent D1 deal lease; no local fallback when cloud mode is selected."""
import json, os, uuid, urllib.request
from smart_dedup import validate

def request(path, payload, opener=None):
    url=os.environ.get('V16_WORKER_URL','').rstrip('/')
    secret=os.environ.get('V16_REGISTRATION_SECRET','')
    if not url.startswith('https://') or not secret:
        raise RuntimeError('V16_D1_NOT_CONFIGURED')
    req=urllib.request.Request(url+path,data=json.dumps(payload).encode(),method='POST',headers={'Authorization':'Bearer '+secret,'Content-Type':'application/json'})
    with (opener or urllib.request.urlopen)(req,timeout=12) as response:
        data=json.load(response)
    return data

def send_once(candidate,sender):
    asin,price=validate(candidate)
    owner=uuid.uuid4().hex
    payload={'asin':asin,'price_cents':price,'owner':owner}
    if request('/dedup/claim',payload).get('allowed') is not True:
        return 'SKIPPED_DUPLICATE'
    delivered=False
    try:
        delivered=bool(sender(candidate))
    finally:
        # If finalize fails after delivery, lease expires after 10 minutes; monitor failures.
        request('/dedup/finish',{**payload,'success':delivered})
    return 'SENT' if delivered else 'SEND_FAILED_RETRY_LATER'

def already_sent(candidate):
    # Read-only optimization; send_once remains authoritative.
    asin, price = validate(candidate)
    result = request('/dedup/check', {
        'asin': asin,
        'price_cents': price,
    })
    if type(result.get('duplicate')) is not bool:
        raise RuntimeError('V16_D1_INVALID_CHECK_RESPONSE')
    return result['duplicate']
