import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/v16'))
from production_discovery import discover
from production_pipeline import run

ASIN = lambda n: f'B{n:09d}'

class FakeTab:
    def __init__(self, url):
        self.url = url
    def goto(self, url, **kwargs):
        self.url = url
    def title(self):
        return 'Amazon Egypt'
    def close(self):
        pass
    def locator(self, selector):
        return self
    def evaluate_all(self, script):
        if self.url.endswith('/deals'):
            return [{'asin': ASIN(1), 'text': 'خصم 10%'}]
        return [{'asin': ASIN(1), 'text': 'خصم 95%'},
                {'asin': ASIN(2), 'text': 'خصم 70%'}]

class FakeContext:
    def new_page(self):
        return FakeTab('')
class FakeBrowser:
    def new_context(self, **kwargs):
        return FakeContext()
    def close(self):
        pass
class FakePlaywright:
    chromium = None
    def __init__(self):
        self.chromium = self
    def launch(self, **kwargs):
        return FakeBrowser()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass

def test_scans_all_sources_and_uses_strongest_duplicate_hint():
    report = discover(max_pages=2, max_candidates=2,
        pages=('https://www.amazon.eg/deals', 'https://www.amazon.eg/gp/goldbox'),
        browser_factory=FakePlaywright)
    assert report['candidates'][0]['asin'] == ASIN(1)
    assert report['candidates'][0]['listing_discount_hint'] == 95
    assert len(report['candidates']) == 2

def test_pipeline_collects_100_but_probes_top_2():
    seen, options = [], []
    def discovery(**kwargs):
        options.append(kwargs)
        return {'candidates': [
            {'asin': ASIN(1), 'listing_discount_hint': 10},
            {'asin': ASIN(2), 'listing_discount_hint': 95},
            {'asin': ASIN(3), 'listing_discount_hint': 70},
        ], 'errors': []}
    def probe(asin):
        seen.append(asin)
        yield {'asin': asin, 'title': 'Coffee', 'current_price': '100',
               'displayed_discount_pct': '4'}, None, None
    result = run(send=False, max_candidates=2, discover_fn=discovery, probe_fn=probe)
    assert options == [{'max_pages': 4, 'max_candidates': 100}]
    assert seen == [ASIN(2), ASIN(3)]
    assert result['discovered'] == 3 and result['probed'] == 2
