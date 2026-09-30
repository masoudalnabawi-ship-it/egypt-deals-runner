from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


STOP = {
    'the','and','with','for','from','new','original','official','edition','version',
    'black','white','blue','red','green','silver','gold','gray','grey','pink',
    'لون','مع','من','في','على','الى','إلى','اصلي','أصلي','جديد','نسخة','اصدار','إصدار',
}

BRANDS = {
    'samsung','apple','xiaomi','redmi','poco','oppo','realme','honor','huawei','nokia','motorola',
    'lenovo','dell','hp','asus','acer','msi','sony','lg','tcl','hisense','philips','anker','jbl',
    'bosch','beko','fresh','tornado','sharp','toshiba','midea','ariston','braun','philips','tefal',
    'samsung','سامسونج','ابل','آبل','شاومي','ريدمي','بوكو','اوبو','أوبو','ريلمي','هونر','هواوي',
}

MODEL_RE = re.compile(r"\b(?:[A-Z]{1,6}[- ]?\d{2,7}[A-Z0-9-]*|\d{2,4}[A-Z]{1,4})\b", re.I)
CAPACITY_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(TB|GB|MB|تيرا|جيجا)\b", re.I)
SIZE_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:inch|inches|in|بوصة|\")\b", re.I)
RAM_RE = re.compile(r"\b(?:ram\s*)?(\d+)\s*(?:gb|جيجا)\s*(?:ram|رام)\b|\b(\d+)\s*(?:gb|جيجا)\s*ram\b", re.I)
PACK_RE = re.compile(r"\b(?:pack of|set of|عدد|عبوة)\s*(\d+)\b", re.I)


def _norm(text: str) -> str:
    s = unicodedata.normalize('NFKC', str(text or '')).lower()
    s = s.replace('×', 'x')
    s = re.sub(r"[^\w.+-]+", ' ', s, flags=re.UNICODE)
    return ' '.join(s.split())


def _capacity_gb(value: float, unit: str) -> int:
    unit = unit.lower()
    if unit in {'tb','تيرا'}:
        return int(round(value * 1024))
    if unit in {'mb'}:
        return int(round(value / 1024))
    return int(round(value))


@dataclass(frozen=True, slots=True)
class ProductSignature:
    brand: str
    models: frozenset[str]
    capacities_gb: frozenset[int]
    sizes_in: frozenset[float]
    ram_gb: frozenset[int]
    pack_counts: frozenset[int]
    tokens: frozenset[str]


def signature(title: str) -> ProductSignature:
    raw = str(title or '')
    n = _norm(raw)
    words = [w for w in n.split() if len(w) >= 2 and w not in STOP and not w.isdigit()]
    brand = next((w for w in words if w in BRANDS), '')

    models = set()

    for match in MODEL_RE.findall(raw):
        if not match:
            continue

        model = re.sub(
            r"[\s-]+",
            "",
            match.upper(),
        )

        # Storage / RAM values such as 256GB or 16GB
        # are specifications, not product model numbers.
        # Treating them as models can make:
        # Galaxy A55 256GB
        # and Galaxy S24 256GB
        # look like the same model.
        if re.fullmatch(
            r"\d+(?:GB|TB|MB)",
            model,
            re.I,
        ):
            continue

        if re.fullmatch(
            r"\d+(?:GB|جيجا)?RAM",
            model,
            re.I,
        ):
            continue

        models.add(model)

    capacities = set()
    for value, unit in CAPACITY_RE.findall(raw):
        try:
            gb = _capacity_gb(float(value), unit)
            if 1 <= gb <= 32768:
                capacities.add(gb)
        except Exception:
            pass

    sizes = set()
    for value in SIZE_RE.findall(raw):
        try:
            v = round(float(value), 1)
            if 1 <= v <= 150:
                sizes.add(v)
        except Exception:
            pass

    ram = set()
    for a, b in RAM_RE.findall(raw):
        value = a or b
        if value:
            try:
                v = int(value)
                if 1 <= v <= 256:
                    ram.add(v)
            except Exception:
                pass

    packs = set()
    for value in PACK_RE.findall(raw):
        try:
            v = int(value)
            if 2 <= v <= 100:
                packs.add(v)
        except Exception:
            pass

    return ProductSignature(
        brand=brand,
        models=frozenset(models),
        capacities_gb=frozenset(capacities),
        sizes_in=frozenset(sizes),
        ram_gb=frozenset(ram),
        pack_counts=frozenset(packs),
        tokens=frozenset(words),
    )


def compatibility(a: ProductSignature, b: ProductSignature) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if a.brand and b.brand and a.brand != b.brand:
        return False, ['brand_mismatch']
    if a.models and b.models and not (a.models & b.models):
        return False, ['model_mismatch']
    if a.capacities_gb and b.capacities_gb and not (a.capacities_gb & b.capacities_gb):
        return False, ['capacity_mismatch']
    if a.ram_gb and b.ram_gb and not (a.ram_gb & b.ram_gb):
        return False, ['ram_mismatch']
    if a.sizes_in and b.sizes_in:
        if min(abs(x-y) for x in a.sizes_in for y in b.sizes_in) > 0.6:
            return False, ['size_mismatch']
    if a.pack_counts and b.pack_counts and not (a.pack_counts & b.pack_counts):
        return False, ['pack_mismatch']
    if a.models and b.models and (a.models & b.models):
        reasons.append('model_match')
    if a.capacities_gb and b.capacities_gb and (a.capacities_gb & b.capacities_gb):
        reasons.append('capacity_match')
    return True, reasons
