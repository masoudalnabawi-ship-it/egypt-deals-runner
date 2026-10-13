import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/v16'))
from production_discovery import valid_source, extract_cards
from production_pipeline import run


def test_source_whitelist():
    assert valid_source('https://www.amazon.eg/deals')
    assert not valid_source('https://www.amazon.eg.evil.com/deals')
    assert not valid_source('http://www.amazon.eg/deals')
    assert not valid_source('https://evil.com/@www.amazon.eg/')


def test_card_dedup_and_hints():
    class Locator:
        def evaluate_all(self, _):
            return [{'asin': 'B012345678', 'text': 'خصم 91%'},
                    {'asin': 'B012345678', 'text': 'خصم 90%'},
                    {'asin': 'B098765432', 'text': 'regular item'}]
    class Page:
        url = 'https://www.amazon.eg/deals'
        def locator(self, _): return Locator()
    cards = extract_cards(Page())
    assert len(cards) == 2
    assert cards[0]['listing_discount_hint'] == 91
    assert cards[1]['listing_discount_hint'] is None


def test_dry_run_never_sends():
    calls = []
    def discovery(**_):
        return {'candidates': [{'asin': 'B012345678'}], 'errors': []}
    def probe(_):
        yield ({'asin': 'B012345678', 'title': 'Test', 'current_price': '100',
                'displayed_discount_pct': '95'}, None, None)
    def alert(_, enabled=False, **kwargs):
        calls.append(enabled)
        return 'DISABLED'
    result = run(send=False, discover_fn=discovery, probe_fn=probe, alert_fn=alert)
    assert result['eligible'] == 1
    assert calls == [False]
