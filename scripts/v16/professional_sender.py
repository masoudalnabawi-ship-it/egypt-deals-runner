"""V16 private photo + caption sender. No public publishing."""
import hashlib
import json
import os
import uuid
from decimal import Decimal, InvalidOperation
import urllib.request
from pathlib import Path

from professional_alert import format_alert, review_keyboard
from telegram_config import token as configured_token, review_chat, interactive_ready


def send(candidate, *, token=None, chat_id=None, opener=None):
    try:
        discount = Decimal(str(candidate.get('displayed_discount_pct')))
    except (InvalidOperation, TypeError, ValueError):
        return False
    if not discount.is_finite() or not 70 <= discount <= 100:
        return False

    token = token if token is not None else configured_token()
    chat_id = chat_id if chat_id is not None else review_chat()

    if not token or not str(chat_id).lstrip('-').isdigit():
        return False

    path = Path(candidate.get('screenshot_path') or '')
    expected_hash = candidate.get('screenshot_sha256')

    if not expected_hash or not path.is_file():
        raise ValueError('V16_REAL_SCREENSHOT_REQUIRED')

    image = path.read_bytes()
    if hashlib.sha256(image).hexdigest() != expected_hash:
        raise ValueError('V16_SCREENSHOT_HASH_MISMATCH')

    caption = format_alert(candidate)
    if len(caption) > 1024:
        raise ValueError('V16_CAPTION_TOO_LONG')

    fields = {
        'chat_id': str(chat_id),
        'caption': caption,
        'reply_markup': review_keyboard(candidate, interactive=False),
    }

    boundary = 'V16-' + uuid.uuid4().hex
    body = bytearray()

    for key, value in fields.items():
        body.extend(
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
            f'{value}\r\n'.encode('utf-8')
        )

    body.extend(
        f'--{boundary}\r\n'
        'Content-Disposition: form-data; name="photo"; filename="amazon-real.jpg"\r\n'
        'Content-Type: image/jpeg\r\n\r\n'.encode('utf-8')
    )
    body.extend(image)
    body.extend(f'\r\n--{boundary}--\r\n'.encode())

    request = urllib.request.Request(
        f'https://api.telegram.org/bot{token}/sendPhoto',
        data=bytes(body),
        headers={'Content-Type': f'multipart/form-data; boundary={boundary}'},
        method='POST',
    )

    with (opener or urllib.request.urlopen)(request, timeout=20) as response:
        result = json.load(response)

    if result.get('ok') is not True:
        return False

    message = result.get('result') or {}
    message_id = message.get('message_id')

    # Register mapping in persistent D1 BEFORE enabling interactive buttons.
    if type(message_id) is int and message_id > 0 and interactive_ready():
        worker = os.environ.get('V16_WORKER_URL','').rstrip('/')
        secret = os.environ.get('V16_REGISTRATION_SECRET','')
        if not worker.startswith('https://') or not secret:
            import logging
            logging.getLogger(__name__).error('V16_INTERACTIVE_CONFIG_MISSING message_id=%s',message_id)
        if worker.startswith('https://') and secret:
            payload = json.dumps({'asin':candidate['asin'],'message_id':message_id,'chat_id':str(chat_id)}).encode()
            req = urllib.request.Request(worker+'/register',data=payload,method='POST',headers={
                'Authorization':'Bearer '+secret,'Content-Type':'application/json'})
            try:
                with urllib.request.urlopen(req,timeout=12) as resp:
                    registered = json.load(resp).get('ok') is True
                if not registered:
                    raise RuntimeError('V16_REVIEW_REGISTRATION_NOT_CONFIRMED')
                if registered:
                    keyboard = json.loads(review_keyboard(candidate,interactive=True))
                    edit = urllib.request.Request(
                        f'https://api.telegram.org/bot{token}/editMessageReplyMarkup',
                        data=json.dumps({'chat_id':str(chat_id),'message_id':message_id,'reply_markup':keyboard}).encode(),
                        method='POST',headers={'Content-Type':'application/json'})
                    with urllib.request.urlopen(edit,timeout=12) as resp:
                        if json.load(resp).get('ok') is not True:
                            raise RuntimeError('V16_BUTTON_ACTIVATION_FAILED')
            except Exception:
                import logging
                logging.getLogger(__name__).exception('V16_INTERACTIVE_SETUP_FAILED message_id=%s',message_id)
                # Safe fallback: photo remains private with product URL only.

    if (type(message_id) is int and message_id > 0
            and os.environ.get('V16_DEDUP_BACKEND') != 'd1'):
        try:
            from review_store import save_review_message_id
            save_review_message_id(candidate['asin'], message_id)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error(
                'V16_REVIEW_MESSAGE_MAPPING_FAILED asin=%s message_id=%s error=%s',
                candidate['asin'],
                message_id,
                type(exc).__name__,
            )

    return True
