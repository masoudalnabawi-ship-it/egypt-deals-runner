import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/v16'))
from production_pipeline import run

ASIN = 'B012345678'
def discover(**kwargs):
    return {'candidates': [{'asin': ASIN}], 'errors': []}
def probe(asin):
    yield ({'asin': asin, 'title': 'test', 'current_price': '100', 'displayed_discount_pct': '91'}, None, None)

def test_duplicate_does_not_trigger_photo(monkeypatch):
    monkeypatch.setenv('V16_PRIVATE_TELEGRAM_ENABLED', '1')
    calls = []
    def alert(_, **kwargs):
        calls.append(kwargs)
        return 'DUPLICATE'
    result = run(send=True, discover_fn=discover, probe_fn=probe, alert_fn=alert)
    assert len(calls) == 1
    assert result['eligible'] == 1

def test_photo_failure_does_not_erase_text_success(monkeypatch):
    monkeypatch.setenv('V16_PRIVATE_TELEGRAM_ENABLED', '1')
    def alert(_, **kwargs):
        if kwargs.get('screenshot_path') is not None or 'screenshot_sha256' in kwargs:
            raise TimeoutError('photo upload failed')
        return 'SENT'
    def probe_with_photo(asin):
        observation = {
            'asin': asin,
            'title': 'test',
            'current_price': '100',
            'displayed_discount_pct': '91',
        }
        yield observation, None, None
        yield observation, 'test-image.jpg', 'test-sha256'

    result = run(
        send=True,
        discover_fn=discover,
        probe_fn=probe_with_photo,
        alert_fn=alert,
    )
    assert result['alerts'][0]['status'] == 'SENT'
    assert result['alerts'][0]['kind'] == 'text'
    assert result['failures'][0]['reason'] == 'PHOTO_TimeoutError'
