"""V16-first Telegram configuration; legacy names are transitional only."""
import os

def token():
    return os.environ.get('V16_TELEGRAM_BOT_TOKEN') or os.environ.get('V15_TELEGRAM_BOT_TOKEN', '')

def review_chat():
    return os.environ.get('V16_TELEGRAM_REVIEW_CHAT_ID') or os.environ.get('V15_TELEGRAM_REVIEW_CHAT_ID', '')

def interactive_ready():
    return (os.environ.get('V16_INTERACTIVE_READY') == '1'
            and os.environ.get('V16_PRIVATE_TELEGRAM_ENABLED') == '1'
            and review_chat().lstrip('-').isdigit()
            and os.environ.get('V16_DEDUP_BACKEND') in ('sqlite', 'd1')
            and bool(os.environ.get('V16_WORKER_URL', '').startswith('https://'))
            and bool(os.environ.get('V16_REGISTRATION_SECRET')))
