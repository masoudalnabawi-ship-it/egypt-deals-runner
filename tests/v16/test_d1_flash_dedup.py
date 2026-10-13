import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/v16'))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/v15'))

import d1_flash_dedup as dedup


class FakeD1:
    def __init__(self):
        self.text = {}
        self.photos = set()
        self.calls = 0

    def query(self, sql):
        import re
        self.calls += 1

        if sql.startswith('CREATE TABLE'):
            return []

        if sql.startswith('INSERT INTO v16_flash_alert_dedup'):
            asin = re.search(r"VALUES \('([^']+)'", sql).group(1)
            price = int(re.search(r"VALUES \('[^']+',([0-9]+)", sql).group(1))
            owner = re.search(r"'sending','([^']+)'", sql).group(1)
            previous = self.text.get(asin)

            if previous and previous['state'] == 'sent' and price >= previous['price']:
                return []

            self.text[asin] = {'price': price, 'state': 'sending', 'owner': owner}
            return [{'owner': owner}]

        if sql.startswith('UPDATE v16_flash_alert_dedup'):
            asin = re.search(r"asin='([^']+)'", sql).group(1)
            self.text[asin]['state'] = 'sent'
            return []

        if sql.startswith('INSERT INTO v16_flash_screenshot_dedup'):
            match = re.search(
                r"VALUES\s*\(\s*'([^']+)'\s*,\s*([0-9]+)\s*,\s*'([^']+)'\s*,\s*'sending'\s*,\s*'([^']+)'",
                sql
            )
            if match is None:
                raise AssertionError('Cannot parse screenshot INSERT SQL: ' + sql[:400])
            asin, price, digest, owner = match.groups()
            key = (asin, int(price), digest)
            if key in self.photos:
                return []
            self.photos.add(key)
            return [{'owner': owner}]

        if sql.startswith('UPDATE v16_flash_screenshot_dedup'):
            return []

        raise AssertionError('Unexpected SQL: ' + sql[:100])


class V16D1Tests(unittest.TestCase):
    def setUp(self):
        self.db = FakeD1()
        self.patcher = patch.object(dedup, 'query', self.db.query)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def offer(self, price):
        return {'asin': 'B012345678', 'current_price': str(price)}

    def test_first_alert_and_same_price_dedup(self):
        sent = []
        sender = lambda c: sent.append(c['current_price']) or True
        self.assertEqual(dedup.send_once(self.offer('100'), sender), 'SENT')
        self.assertEqual(
            dedup.send_once(self.offer('100'), sender),
            'SKIPPED_DUPLICATE'
        )
        self.assertEqual(sent, ['100'])

    def test_one_cent_price_drop_triggers_alert(self):
        sent = []
        sender = lambda c: sent.append(c['current_price']) or True
        self.assertEqual(dedup.send_once(self.offer('100'), sender), 'SENT')
        self.assertEqual(dedup.send_once(self.offer('99.99'), sender), 'SENT')
        self.assertEqual(sent, ['100', '99.99'])

    def test_price_increase_does_not_repeat(self):
        sender = lambda c: True
        self.assertEqual(dedup.send_once(self.offer('100'), sender), 'SENT')
        self.assertEqual(
            dedup.send_once(self.offer('101'), sender),
            'SKIPPED_DUPLICATE'
        )

    def test_same_photo_dedup(self):
        candidate = self.offer('100')
        candidate['screenshot_sha256'] = 'a' * 64
        sender = lambda c: True
        self.assertEqual(
            dedup.send_screenshot_once(candidate, sender),
            'SCREENSHOT_SENT'
        )
        self.assertEqual(
            dedup.send_screenshot_once(candidate, sender),
            'SKIPPED_SCREENSHOT_DUPLICATE'
        )


    def test_failed_text_send_does_not_claim_success(self):
        candidate = self.offer('100')
        self.assertEqual(
            dedup.send_once(candidate, lambda c: False),
            'SEND_FAILED_RETRY_LATER'
        )
        self.assertEqual(
            self.db.text[candidate['asin']]['state'],
            'sending'
        )

    def test_failed_photo_send_does_not_claim_success(self):
        candidate = self.offer('100')
        candidate['screenshot_sha256'] = 'b' * 64
        self.assertEqual(
            dedup.send_screenshot_once(candidate, lambda c: False),
            'SCREENSHOT_RETRY_LATER'
        )


if __name__ == '__main__':
    unittest.main()
