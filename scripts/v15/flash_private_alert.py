"""V15 only: best-effort private early warning; never publishes publicly."""
import json
import os
import re
import urllib.parse
import urllib.request
from decimal import Decimal
from flash_review import keyboard, interactive_enabled

ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")

def payload(candidate):
    asin = str(candidate.get("asin", ""))
    if not ASIN_RE.fullmatch(asin):
        raise ValueError("INVALID_ASIN")

    price = Decimal(str(candidate["current_price"]))
    if not price.is_finite() or price <= 0:
        raise ValueError("INVALID_PRICE")

    name = str(candidate.get("title") or candidate.get("name") or "منتج على أمازون مصر")
    name = re.sub(r"[\\x00-\\x1f\\x7f]", " ", name).strip()[:180]

    if candidate.get("review_type") == "PRICE_ONLY":
        text = (
            f"🛍️ منتج يستحق المراجعة | أمازون مصر 🇪🇬\n\n"
            f"📦 {name}\n\n"
            f"💰 السعر المرصود: {price:,.2f} جنيه\n\n"
            "🔎 لا يوجد خصم تاريخي مؤكد.\n"
            "⚠️ راجع السعر والتوافر قبل اتخاذ القرار.\n\n"
            "🔒 مراجعة خاصة فقط — النشر العام معطّل."
        )
    else:
        reference = Decimal(str(candidate["displayed_reference"]))
        discount = Decimal(str(candidate["displayed_discount_pct"]))
        if not (
            reference.is_finite()
            and discount.is_finite()
            and 0 < price < reference
            and 70 <= discount < 100
        ):
            raise ValueError("INVALID_FLASH_PRICE")

        text = (
            f"🔥 عرض مميز على أمازون مصر! 🇪🇬\n\n"
            f"🛍️ {name}\n\n"
            f"💰 السعر المرصود: {price:,.2f} جنيه\n"
            f"🏷️ السعر المرجعي المعروض: {reference:,.2f} جنيه\n"
            f"🔥 الخصم الظاهر: {discount}%\n\n"
            "⚠️ السعر المرجعي ليس تاريخ سعر موثقًا.\n"
            "🔎 العرض قيد المراجعة والتحقق.\n"
            "🔒 لا يوجد نشر عام."
        )

    return {
        "text": text,
        "reply_markup": json.dumps(
            keyboard(candidate, interactive=interactive_enabled()),
            ensure_ascii=False,
        ),
    }


def send(candidate, *, token=None, chat_id=None, opener=None):
    """Send a private Telegram alert with verified screenshot when available."""
    import hashlib
    import mimetypes
    import uuid
    from pathlib import Path

    token = token if token is not None else os.environ.get("V15_TELEGRAM_BOT_TOKEN", "")
    chat_id = chat_id if chat_id is not None else os.environ.get("V15_TELEGRAM_REVIEW_CHAT_ID", "")

    if not token or not re.fullmatch(r"-?\\d+", str(chat_id).strip()):
        return False

    data = payload(candidate)
    data["chat_id"] = str(chat_id).strip()

    screenshot_path = candidate.get("screenshot_path")
    screenshot_hash = candidate.get("screenshot_sha256")

    if screenshot_path and screenshot_hash:
        screenshot = Path(screenshot_path)

        if screenshot.is_file():
            image_bytes = screenshot.read_bytes()
            actual_hash = hashlib.sha256(image_bytes).hexdigest()

            if actual_hash != screenshot_hash:
                raise RuntimeError("V15_TELEGRAM_SCREENSHOT_HASH_MISMATCH")

            boundary = "V15-" + uuid.uuid4().hex
            fields = dict(data)
            fields["caption"] = fields.pop("text")[:1024]

            body = bytearray()

            for key, value in fields.items():
                body.extend(("--" + boundary + "\\r\\n").encode())
                body.extend(
                    ('Content-Disposition: form-data; name="' + key + '"\\r\\n\\r\\n').encode()
                )
                body.extend(str(value).encode("utf-8"))
                body.extend(b"\\r\\n")

            body.extend(("--" + boundary + "\\r\\n").encode())
            body.extend(
                b'Content-Disposition: form-data; name="photo"; filename="amazon-product.jpg"\\r\\n'
            )
            body.extend(b"Content-Type: image/jpeg\\r\\n\\r\\n")
            body.extend(image_bytes)
            body.extend(b"\\r\\n")
            body.extend(("--" + boundary + "--\\r\\n").encode())

            req = urllib.request.Request(
                "https://api.telegram.org/bot" + token + "/sendPhoto",
                data=bytes(body),
                headers={"Content-Type": "multipart/form-data; boundary=" + boundary},
                method="POST",
            )
            op = opener or urllib.request.urlopen
            with op(req, timeout=20) as response:
                return json.load(response).get("ok") is True

    req = urllib.request.Request(
        "https://api.telegram.org/bot" + token + "/sendMessage",
        data=urllib.parse.urlencode(data).encode(),
        method="POST",
    )
    op = opener or urllib.request.urlopen
    with op(req, timeout=12) as response:
        return json.load(response).get("ok") is True
