"""V15-only private Telegram connectivity check; never logs credentials or API response bodies."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request


def main():
    token = os.getenv('V15_TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.getenv('V15_TELEGRAM_REVIEW_CHAT_ID', '').strip()
    if not token or not chat_id:
        print('V15_TELEGRAM_CONFIG_MISSING')
        return 1
    if not chat_id.lstrip('-').isdigit():
        print('V15_TELEGRAM_CHAT_ID_NOT_NUMERIC')
        return 1
    data = urllib.parse.urlencode({
        'chat_id': chat_id,
        'text': '⚡ Egypt Deal Hunter V15\n✅ اختبار الاتصال ناجح\n🔒 النشر العام غير مفعل',
    }).encode('utf-8')
    request = urllib.request.Request(
        'https://api.telegram.org/bot' + token + '/sendMessage',
        data=data, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.load(response)
        if result.get('ok') is True:
            print('V15_TELEGRAM_PRIVATE_TEST_SUCCESS')
            return 0
        print('V15_TELEGRAM_API_NOT_OK')
    except urllib.error.HTTPError as exc:
        # Never print the URL, HTTPError object, response body, or token.
        print('V15_TELEGRAM_HTTP_STATUS', exc.code)
        if exc.code == 400:
            print('V15_TELEGRAM_HINT_CHECK_CHAT_ID_AND_START')
        elif exc.code == 401:
            print('V15_TELEGRAM_HINT_INVALID_OR_REVOKED_TOKEN')
        elif exc.code == 403:
            print('V15_TELEGRAM_HINT_BOT_BLOCKED_OR_CHAT_FORBIDDEN')
    except (urllib.error.URLError, TimeoutError):
        print('V15_TELEGRAM_NETWORK_ERROR')
    except (ValueError, OSError):
        print('V15_TELEGRAM_RESPONSE_ERROR')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
