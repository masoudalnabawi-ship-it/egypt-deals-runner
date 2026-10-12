"""V15 read-only flash candidate classification. No messages, no publication."""
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from book_filter import from_report

def candidate(report, threshold=Decimal('70')):
    if from_report(report):return None
    obs=report.get('observation') or {}
    if not isinstance(obs,dict) or obs.get('page_asin')!=report.get('asin'):return None
    try:
        current=Decimal(str(obs.get('current_price')))
        old=Decimal(str(obs.get('old_price')))
    except (InvalidOperation, ValueError, TypeError):return None
    if not all(v.is_finite() and v>0 for v in (current,old)) or old<=current:return None
    pct=(old-current)*100/old
    if pct<threshold:return None
    return {'asin':report['asin'],'url':report.get('url'),
            'current_price':str(current),'displayed_reference':str(old),
            'displayed_discount_pct':str(pct.quantize(Decimal('0.01'))),
            'captured_at':report.get('captured_at'),
            'status':'UNVERIFIED_REFERENCE','publication_allowed':False,
            'note':'Displayed reference price is not verified historical price'}

def stage(report, output_dir):
    item=candidate(report)
    if item is None:return None
    out=Path(output_dir);out.mkdir(parents=True,exist_ok=True)
    path=out/(item['asin']+'.json')
    path.write_text(json.dumps(item,ensure_ascii=False,indent=2),encoding='utf-8')
    return path
