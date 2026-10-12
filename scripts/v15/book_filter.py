"""Conservative V15-only exclusion of books and book-cover accessories."""
import re
import unicodedata

# Explicitly known unwanted product from operator's real-world evidence.
BLOCKED_ASINS = frozenset({'0345520378'})
CATEGORIES = frozenset({'books', 'book', 'kindle books', 'ebooks', 'literature', 'magazines', 'newspapers', 'printed books', 'الكتب', 'كتب', 'روايات', 'مجلات'})
# Avoid blanket matching 'book', 'cover', 'notebook' or 'case' in titles.
PRINT_TERMS = re.compile(r'\b(?:paperback|hardcover|hardback|mass market paperback|kindle edition|ebook edition|novel|fiction novel|book volume|book series|reading book|story book|textbook|workbook|comic book|book jacket|book dust jacket|book sleeve|book protector|book cover|quran cover|bible cover)\b',re.I)
ARABIC_TERMS = re.compile(r'(?:رواية|روايات|كتاب ورقي|كتاب إلكتروني|كتاب الكتروني|كتاب مدرسي|غلاف كتاب|غلاف مصحف|حافظة كتاب|جراب كتاب|قصص أطفال|مجلة ورقية|تجليد كتب)')
SAFE_TERMS = re.compile(r'\b(?:macbook|chromebook|notebook laptop|laptop notebook|notebook computer|bookcase|bookshelf|book light|book scanner|book stand|e-?reader|kindle paperwhite|kindle oasis|kindle scribe)\b',re.I)

def isbn10_valid(value):
    value=(value or '').upper().replace('-','').replace(' ','')
    if not re.fullmatch(r'[0-9]{9}[0-9X]',value):return False
    return sum((10-i)*(10 if x=='X' else int(x)) for i,x in enumerate(value))%11==0

def norm(value):
    return unicodedata.normalize('NFKC',str(value or '')).casefold().strip()

def classify(asin='',title='',category='',product_type='',isbn='',description=''):
    asin=norm(asin).upper();title=norm(title);cat=norm(category);typ=norm(product_type)
    if asin in BLOCKED_ASINS:return 'known_book_asin'
    if any(x in CATEGORIES for x in (cat,typ)):return 'book_category'
    if isbn10_valid(isbn) or (str(isbn or '').startswith(('978','979')) and len(re.sub(r'\D','',str(isbn)))==13):return 'isbn_metadata'
    # ISBN-shaped ASINs alone are not proof of book identity; metadata required.
    if SAFE_TERMS.search(title) and not (PRINT_TERMS.search(title) or ARABIC_TERMS.search(title)):return None
    if PRINT_TERMS.search(title) or ARABIC_TERMS.search(title):return 'book_title'
    if 'book' in typ and not any(s in typ for s in ('reader','accessor','electronic')):return 'book_product_type'
    return None

def from_report(report):
    obs=report.get('observation') or {}
    if not isinstance(obs,dict):obs={}
    return classify(asin=report.get('asin'),title=obs.get('title') or obs.get('product_title') or obs.get('name') or report.get('title'),category=obs.get('category') or obs.get('department') or report.get('category'),product_type=obs.get('product_type') or report.get('product_type'),isbn=obs.get('isbn') or report.get('isbn'))
