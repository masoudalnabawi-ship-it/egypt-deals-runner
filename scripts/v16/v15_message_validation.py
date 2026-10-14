"""Standalone V16 message validation; does not modify V15."""
def validate_message(message, *, max_length=900):
    if not isinstance(message, str):
        raise ValueError('INVALID_MESSAGE')
    message = message.strip()
    if not message or len(message) > max_length:
        raise ValueError('INVALID_MESSAGE')
    if any(ord(char) < 32 and char not in '\n\t' for char in message):
        raise ValueError('INVALID_MESSAGE')
    return message
