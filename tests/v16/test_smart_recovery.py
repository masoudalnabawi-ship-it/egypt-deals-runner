import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/v16"))

from fast_probe import inspect_with_recovery


ASIN = "B012345678"
URL = f"https://www.amazon.eg/dp/{ASIN}"


def make_page(body):
    page = Mock()
    page.locator.return_value.inner_text.return_value = body
    return page


def test_incomplete_page_recovers():
    page = make_page("Amazon.eg")
    inspector = Mock(
        side_effect=[
            RuntimeError("no_live_price"),
            {"current_price": 100, "page_asin": ASIN},
        ]
    )
    result = inspect_with_recovery(
        page, URL, ASIN, inspector, lambda _: False
    )
    assert result["current_price"] == 100
    assert inspector.call_count == 2


def test_blocked_page_not_retried():
    page = make_page("Amazon.eg")
    inspector = Mock(side_effect=RuntimeError("no_live_price"))
    with pytest.raises(RuntimeError, match="no_live_price"):
        inspect_with_recovery(
            page, URL, ASIN, inspector, lambda _: True
        )
    assert inspector.call_count == 1


def test_complete_page_without_price_not_retried():
    page = make_page("Product details " * 30)
    inspector = Mock(side_effect=RuntimeError("no_live_price"))
    with pytest.raises(RuntimeError, match="no_live_price"):
        inspect_with_recovery(
            page, URL, ASIN, inspector, lambda _: False
        )
    assert inspector.call_count == 1


def test_second_failure_propagates():
    page = make_page("Amazon.eg")
    inspector = Mock(
        side_effect=[
            RuntimeError("no_live_price"),
            RuntimeError("amazon_blocked"),
        ]
    )
    with pytest.raises(RuntimeError, match="amazon_blocked"):
        inspect_with_recovery(
            page, URL, ASIN, inspector, lambda _: False
        )
    assert inspector.call_count == 2
