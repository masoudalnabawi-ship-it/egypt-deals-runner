import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/v16'))
from screenshot_flash import send_flash

OFFER = {'asin': 'B012345678', 'current_price': '100', 'displayed_discount_pct': '90'}


def test_urgent_send_never_initializes_d1():
    calls = []
    with patch.dict(os.environ, {
        'V16_PRIVATE_TELEGRAM_ENABLED': '1',
        'V15_TELEGRAM_BOT_TOKEN': 'dummy',
        'V15_TELEGRAM_REVIEW_CHAT_ID': 'dummy',
    }):
        result = send_flash(
            OFFER, enabled=True, sender=lambda _: True,
            initialize=lambda: calls.append('schema-init'),
            send_once=lambda c, sender: calls.append('send') or 'SENT',
            send_screenshot_once=lambda c, sender: 'SCREENSHOT_SENT',
        )
    assert result == 'SENT'
    assert calls == ['send']
