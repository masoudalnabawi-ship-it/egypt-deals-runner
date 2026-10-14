"""V16 Telegram review command validation. No network calls."""
import os
import re
from telegram_config import review_chat

CALLBACK_RE = re.compile(
    r'^v16:(publish|reject|edit|custom):([A-Z0-9]{10})$'
)


def authorized_admin(user_id):
    """Fail closed unless the Telegram user ID is explicitly configured."""
    configured = os.environ.get('V16_TELEGRAM_ADMIN_ID', '').strip()

    if not configured.isdigit():
        return False

    try:
        return int(user_id) == int(configured)
    except (TypeError, ValueError):
        return False


def parse_callback(data):
    """Accept only supported V16 actions with a valid ASIN."""
    if not isinstance(data, str):
        raise ValueError('INVALID_CALLBACK')

    match = CALLBACK_RE.fullmatch(data)

    if match is None:
        raise ValueError('INVALID_CALLBACK')

    return {
        'action': match.group(1),
        'asin': match.group(2),
    }


def validate_callback(callback):
    """Validate admin identity and private review chat."""
    if not isinstance(callback, dict):
        raise ValueError('INVALID_CALLBACK')

    sender = callback.get('from') or {}
    message = callback.get('message') or {}
    chat = message.get('chat') or {}

    if not authorized_admin(sender.get('id')):
        raise PermissionError('UNAUTHORIZED_ADMIN')

    configured_chat = review_chat().strip()

    if not configured_chat or str(chat.get('id')) != configured_chat:
        raise PermissionError('UNAUTHORIZED_REVIEW_CHAT')

    if type(message.get('message_id')) is not int or message['message_id'] <= 0:
        raise PermissionError('INVALID_REVIEW_MESSAGE')
    return parse_callback(callback.get('data'))
