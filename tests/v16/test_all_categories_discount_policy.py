import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/v16'))
from screenshot_flash import candidate_from_observation
from production_discovery import DISCOUNT

BASE = {'asin': 'B012345678', 'title': 'Coffee and groceries', 'current_price': '100'}


def offer(pct, title=None):
    return candidate_from_observation({**BASE, 'displayed_discount_pct': str(pct),
                                       'title': title or BASE['title']})


def test_discount_boundary():
    assert offer('4.99') is None
    assert offer('5')['category'] == 'STANDARD'
    assert offer('29.99')['category'] == 'STANDARD'
    assert offer('30')['category'] == 'GOOD'
    assert offer('49.99')['category'] == 'GOOD'
    assert offer('50')['category'] == 'ULTRA'
    assert offer('70')['category'] == 'SUPER_ULTRA'
    assert offer('90')['category'] == 'FLASH'
    assert offer('100')['category'] == 'FLASH'


def test_all_nonbook_categories_including_groceries():
    for title in ('Rice 5kg', 'Coffee', 'Smartphone', 'Kitchen blender',
                  'Car accessories', 'Baby diapers', 'Sports shoes', 'Pet food',
                  'Office notebook', 'Bookcase', 'مستلزمات البقالة'):
        assert offer(5, title), title


def test_books_novels_and_book_covers_excluded():
    for title in ('Paperback novel', 'E-book', 'Kindle book', 'AudioBook',
                  'Book cover', 'Book jacket', 'رواية جديدة', 'كتاب تعليمي',
                  'غلاف كتاب', 'أغلفة الكتب', 'روايات عربية'):
        assert offer(90, title) is None, title


def test_listing_hints_support_100():
    assert DISCOUNT.findall('خصم 100%')
    assert DISCOUNT.findall('خصم 5%')
