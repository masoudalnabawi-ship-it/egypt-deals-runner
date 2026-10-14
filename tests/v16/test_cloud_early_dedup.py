import unittest
from unittest.mock import patch

from cloud_dedup import already_sent


class CloudEarlyDedupTests(unittest.TestCase):

    def setUp(self):
        self.candidate = {
            'asin': 'B012345678',
            'current_price': 123.45,
        }

    @patch('cloud_dedup.request')
    def test_duplicate_skipped_before_screenshot(self, mock_request):
        mock_request.return_value = {'duplicate': True}

        self.assertTrue(already_sent(self.candidate))

        mock_request.assert_called_once_with(
            '/dedup/check',
            {'asin': 'B012345678', 'price_cents': 12345},
        )

    @patch('cloud_dedup.request')
    def test_new_offer_allowed(self, mock_request):
        mock_request.return_value = {'duplicate': False}

        self.assertFalse(already_sent(self.candidate))

    @patch('cloud_dedup.request')
    def test_invalid_cloud_response_fails_closed(self, mock_request):
        mock_request.return_value = {}

        with self.assertRaises(RuntimeError):
            already_sent(self.candidate)


if __name__ == '__main__':
    unittest.main()
