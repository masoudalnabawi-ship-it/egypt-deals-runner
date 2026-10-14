"""V16 Telegram callback receiver. Disabled unless explicitly started."""
import json
import os
import urllib.parse
import urllib.request

from review_handler import handle_callback
from telegram_config import token as configured_token, review_chat


def telegram_api(method, payload, *, token=None, opener=None):
    token = token or configured_token()
    if not token:
        raise RuntimeError('TELEGRAM_TOKEN_REQUIRED')

    data = urllib.parse.urlencode(payload).encode('utf-8')
    request = urllib.request.Request(
        f'https://api.telegram.org/bot{token}/{method}',
        data=data,
        method='POST',
    )

    with (opener or urllib.request.urlopen)(request, timeout=25) as response:
        result = json.load(response)

    if not result.get('ok'):
        raise RuntimeError('TELEGRAM_API_FAILED')

    return result['result']


def process_update(update, *, api=telegram_api):
    """Process one callback; never publish to a public channel."""
    callback = update.get('callback_query')
    if not callback:
        return {'status': 'IGNORED'}

    callback_id = callback.get('id')
    if not isinstance(callback_id, str) or not callback_id:
        raise ValueError('CALLBACK_ID_REQUIRED')

    try:
        result = handle_callback(callback)
        message = result['message']
    except PermissionError:
        result = {'status': 'UNAUTHORIZED'}
        message = '⛔ غير مصرح لك بتنفيذ هذا الأمر.'
    except ValueError:
        result = {'status': 'INVALID_CALLBACK'}
        message = '⚠️ أمر غير صالح.'

    # Ask for a reply to the exact review photo; never accept free-floating edits.
    if result.get('status') in ('EDITING', 'CUSTOM'):
        from review_store import set_state
        prompt = ('✏️ اكتب النص المعدّل بالرد على صورة العرض نفسها.'
                  if result['status'] == 'EDITING' else
                  '📝 اكتب رسالتك المخصصة بالرد على صورة العرض نفسها.')
        try:
            api('sendMessage', {
                'chat_id': review_chat(), 'text': prompt,
                'reply_to_message_id': callback['message']['message_id'],
            })
        except Exception:
            # Never pretend the editing flow is usable when prompting failed.
            set_state(result['asin'], 'pending')
            raise

    api('answerCallbackQuery', {
        'callback_query_id': callback_id,
        'text': message[:200],
        'show_alert': 'true',
    })

    return result


def poll_once(*, offset=None, api=telegram_api):
    """Fetch one update batch without automatically starting a loop."""
    params = {'timeout': 0, 'limit': 20}
    if offset is not None:
        params['offset'] = int(offset)

    updates = api('getUpdates', params)
    results = []

    for update in updates:
        results.append({
            'update_id': update['update_id'],
            'result': process_update(update, api=api),
        })

    return results


def process_text_update(update, *, resolve_asin, api=None):
    """Save admin reply only for an offer awaiting text editing.

    resolve_asin(reply_message_id) must look up a previously stored
    Telegram review message ID; never trust an ASIN typed by a user.
    """
    from review_security import authorized_admin
    from review_store import get_state, save_message, set_state

    message = update.get('message')
    if not isinstance(message, dict):
        return {'status': 'IGNORED'}

    sender = message.get('from') or {}
    chat = message.get('chat') or {}

    if not authorized_admin(sender.get('id')):
        return {'status': 'UNAUTHORIZED'}

    expected_chat = review_chat().strip()
    if not expected_chat or str(chat.get('id')) != expected_chat:
        return {'status': 'UNAUTHORIZED_CHAT'}

    reply = message.get('reply_to_message') or {}
    reply_id = reply.get('message_id')

    if not isinstance(reply_id, int) or isinstance(reply_id, bool):
        return {'status': 'REPLY_REQUIRED'}

    asin = resolve_asin(reply_id)
    if not asin:
        return {'status': 'UNKNOWN_REVIEW_MESSAGE'}

    state = get_state(asin)
    if state not in ('editing', 'custom'):
        return {'status': 'NOT_AWAITING_TEXT', 'asin': asin}

    try:
        saved = save_message(asin, message.get('text'))
    except ValueError:
        return {'status': 'INVALID_MESSAGE', 'asin': asin}

    # Keep state in editing/custom if Telegram update fails; retry safely.
    if api is not None:
        api('editMessageCaption', {
            'chat_id': expected_chat,
            'message_id': reply_id,
            'caption': saved,
        })
        api('sendMessage', {
            'chat_id': expected_chat,
            'text': f'✅ تم تحديث نص العرض {asin} في رسالة الصورة الأصلية.\n🔒 لا يوجد نشر عام.',
        })
    set_state(asin, 'pending')

    return {
        'status': 'MESSAGE_SAVED',
        'asin': asin,
        'previous_state': state,
        'message_length': len(saved),
    }


def dispatch_update(update, *, api=telegram_api,
                    resolve_asin=None):
    """Route Telegram updates without enabling public publishing."""
    from review_store import resolve_review_asin

    if not isinstance(update, dict):
        raise ValueError('INVALID_UPDATE')

    if 'callback_query' in update:
        return process_update(update, api=api)

    if 'message' in update:
        resolver = resolve_asin or resolve_review_asin
        return process_text_update(
            update,
            resolve_asin=resolver,
            api=api,
        )

    return {'status': 'IGNORED'}


def dispatch_once(update, *, api=telegram_api, resolve_asin=None):
    """Process each Telegram update once using the persistent SQLite ledger."""
    from review_updates import claim_update, finish_update, release_update

    if not isinstance(update, dict):
        raise ValueError('INVALID_UPDATE')

    update_id = update.get('update_id')

    if type(update_id) is not int or update_id < 0:
        raise ValueError('INVALID_UPDATE_ID')

    if not claim_update(update_id):
        return {
            'status': 'SKIPPED_DUPLICATE_UPDATE',
            'update_id': update_id,
        }

    try:
        result = dispatch_update(
            update,
            api=api,
            resolve_asin=resolve_asin,
        )
        if not finish_update(update_id):
            raise RuntimeError('UPDATE_FINISH_FAILED')
        return result
    except Exception:
        release_update(update_id)
        raise


def poll_and_dispatch(*, api=telegram_api):
    """Process a single Telegram update batch with persistent offset.

    Does not start background polling or enable public publishing.
    """
    from review_offset import get_offset, save_offset

    offset = get_offset()

    params = {
        'timeout': 0,
        'limit': 20,
        'allowed_updates': json.dumps(
            ['callback_query', 'message']
        ),
    }

    if offset is not None:
        params['offset'] = offset

    updates = api('getUpdates', params)

    if not isinstance(updates, list):
        raise RuntimeError('INVALID_TELEGRAM_UPDATES')

    results = []

    for update in sorted(
        updates,
        key=lambda item: item['update_id'],
    ):
        update_id = update['update_id']

        result = dispatch_once(update, api=api)

        save_offset(update_id + 1)

        results.append({
            'update_id': update_id,
            'result': result,
        })

    return results
