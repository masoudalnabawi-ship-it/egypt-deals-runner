import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts/v15'))
from book_filter import classify,from_report,isbn10_valid
class BookFilterTests(unittest.TestCase):
 def test_known_real_book(self):self.assertEqual(classify(asin='0345520378',category='home'),'known_book_asin')
 def test_isbn10(self):self.assertTrue(isbn10_valid('0345520378'))
 def test_book_category(self):self.assertEqual(classify(title='Unknown title',category='books'),'book_category')
 def test_books_in_home(self):self.assertEqual(classify(title='Almost Home: The Chesapeake Diaries: 3 (Paperback)',category='home'),'book_title')
 def test_book_cover(self):self.assertEqual(classify(title='Waterproof book cover'),'book_title')
 def test_arabic(self):self.assertEqual(classify(title='رواية جديدة'),'book_title')
 def test_macbook(self):self.assertIsNone(classify(title='Apple MacBook Air M4',category='electronics'))
 def test_notebook(self):self.assertIsNone(classify(title='Notebook Laptop 15 inch',category='computers'))
 def test_phone_case(self):self.assertIsNone(classify(title='Phone protective cover',category='electronics'))
 def test_tv(self):self.assertIsNone(classify(title='LG 50 inch 4K UHD Smart TV',category='electronics'))
 def test_report(self):self.assertEqual(from_report({'asin':'B012345678','observation':{'title':'Great novel paperback','category':'home'}}),'book_title')
 def test_non_book(self):self.assertIsNone(classify(asin='B07H34GDVW',title='Wireless headphones',category='electronics'))
