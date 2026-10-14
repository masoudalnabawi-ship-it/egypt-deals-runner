"""V16 review callback dispatcher with persistent local state."""
from review_security import validate_callback
from review_store import set_state, get_state, resolve_review_asin


def handle_callback(callback):
    """Authorize admin, validate action, then update review state."""
    command = validate_callback(callback)
    action = command['action']
    asin = command['asin']

    message = callback.get('message') or {}
    message_id = message.get('message_id')

    if type(message_id) is not int or resolve_review_asin(message_id) != asin:
        raise PermissionError('REVIEW_MESSAGE_MISMATCH')

    if action == 'publish':
        return {
            'status': 'PUBLISH_DISABLED',
            'asin': asin,
            'message': '🔒 النشر العام غير مفعّل حاليًا.',
        }

    states = {
        'reject': ('rejected', 'REJECTED', '❌ تم رفض العرض.'),
        'edit': ('editing', 'EDITING', '✏️ العرض في انتظار تعديل الرسالة.'),
        'custom': ('custom', 'CUSTOM', '📝 العرض في انتظار رسالة مخصصة.'),
    }

    if action not in states:
        raise ValueError('UNSUPPORTED_ACTION')

    state, status, message = states[action]
    set_state(asin, state)

    return {
        'status': status,
        'asin': asin,
        'state': get_state(asin),
        'message': message,
    }
