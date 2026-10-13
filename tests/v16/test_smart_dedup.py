import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/v16'))
from smart_dedup import send_once

def offer(price):
    return {'asin':'B012345678','current_price':str(price)}

def test_new_same_higher_and_lower(monkeypatch, tmp_path):
    monkeypatch.setenv('V16_DEDUP_DB',str(tmp_path/'v16.sqlite'))
    sent=[]
    def sender(c):
        sent.append(c['current_price']); return True
    assert send_once(offer(100),sender)=='SENT'
    assert send_once(offer(100),sender)=='SKIPPED_DUPLICATE'
    assert send_once(offer(110),sender)=='SKIPPED_DUPLICATE'
    assert send_once(offer(99.99),sender)=='SENT'
    assert sent==['100','99.99']

def test_failed_send_is_retryable(monkeypatch,tmp_path):
    monkeypatch.setenv('V16_DEDUP_DB',str(tmp_path/'v16.sqlite'))
    assert send_once(offer(100),lambda c:False)=='SEND_FAILED_RETRY_LATER'
    assert send_once(offer(100),lambda c:True)=='SENT'

def test_invalid_and_missing_db(monkeypatch,tmp_path):
    import pytest
    monkeypatch.delenv('V16_DEDUP_DB',raising=False)
    with pytest.raises(RuntimeError,match='V16_DEDUP_DB_REQUIRED'):
        send_once(offer(100),lambda c:True)
    monkeypatch.setenv('V16_DEDUP_DB',str(tmp_path/'v16.sqlite'))
    with pytest.raises(ValueError,match='INVALID_PRICE'):
        send_once(offer('nan'),lambda c:True)
