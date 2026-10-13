import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/v16"))

from production_pipeline import run


def discovery(**kwargs):
    return {"candidates": [{"asin": "B012345678"}], "errors": []}


def observation(discount):
    return {
        "asin": "B012345678",
        "title": "Test product",
        "current_price": "100",
        "displayed_discount_pct": str(discount),
    }


def test_no_screenshot_below_threshold():
    events = []

    def probe(asin):
        try:
            yield observation(4.99), None, None
            events.append("SCREENSHOT_CAPTURED")
            yield observation(4.99), "image.png", "digest"
        finally:
            events.append("BROWSER_CLOSED")

    result = run(send=False, discover_fn=discovery, probe_fn=probe)
    assert "SCREENSHOT_CAPTURED" not in events
    assert "BROWSER_CLOSED" in events
    assert result["eligible"] == 0


def test_no_screenshot_when_sending_disabled():
    events = []

    def probe(asin):
        try:
            yield observation(90), None, None
            events.append("SCREENSHOT_CAPTURED")
            yield observation(90), "image.png", "digest"
        finally:
            events.append("BROWSER_CLOSED")

    result = run(send=False, discover_fn=discovery, probe_fn=probe)
    assert "SCREENSHOT_CAPTURED" not in events
    assert "BROWSER_CLOSED" in events
    assert result["eligible"] == 1


def test_no_screenshot_for_duplicate_text(monkeypatch):
    monkeypatch.setenv("V16_PRIVATE_TELEGRAM_ENABLED", "1")
    events = []

    def probe(asin):
        try:
            yield observation(90), None, None
            events.append("SCREENSHOT_CAPTURED")
            yield observation(90), "image.png", "digest"
        finally:
            events.append("BROWSER_CLOSED")

    result = run(
        send=True,
        discover_fn=discovery,
        probe_fn=probe,
        alert_fn=lambda *args, **kwargs: "SKIPPED_DUPLICATE",
    )

    assert "SCREENSHOT_CAPTURED" not in events
    assert "BROWSER_CLOSED" in events
    assert result["alerts"][0]["status"] == "SKIPPED_DUPLICATE"
