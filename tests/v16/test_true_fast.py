import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/v16'))
from production_pipeline import run
ASIN = 'B012345678'
def discover(**_): return {'candidates': [{'asin': ASIN}], 'errors': []}
def test_text_before_screenshot(monkeypatch):
    monkeypatch.setenv('V16_PRIVATE_TELEGRAM_ENABLED', '1')
    order = []
    obs = {'asin': ASIN, 'title': 'test', 'current_price': '100', 'displayed_discount_pct': '91'}
    def probe(_):
        order.append('inspect')
        yield obs, None, None
        order.append('screenshot')
        yield obs, '/tmp/example.jpg', 'hash'
    def alert(_, **kw):
        order.append('photo' if kw.get('screenshot_path') else 'text')
        return 'SENT'
    result = run(send=True, discover_fn=discover, probe_fn=probe, alert_fn=alert)
    assert order == ['inspect', 'text', 'screenshot', 'photo']
    assert result['probed'] == 1 and result['eligible'] == 1

def test_photo_failure_preserves_text(monkeypatch):
    monkeypatch.setenv('V16_PRIVATE_TELEGRAM_ENABLED', '1')
    obs = {'asin': ASIN, 'title': 'test', 'current_price': '100', 'displayed_discount_pct': '91'}
    def probe(_):
        yield obs, None, None
        raise RuntimeError('image failure')
    result = run(send=True, discover_fn=discover, probe_fn=probe,
                 alert_fn=lambda *_a, **_k: 'SENT')
    assert result['alerts'][0]['status'] == 'SENT'
    assert result['failures'][0]['reason'] == 'RuntimeError'
