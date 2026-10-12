import sys,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts/v15'))
from flash_candidate import candidate,stage
class FlashTests(unittest.TestCase):
 def report(self,asin='B0ABC12345',price='2000',old='18749'):
  return {'asin':asin,'url':'https://www.amazon.eg/dp/'+asin,'captured_at':'2026-10-12T08:00:00Z','observation':{'page_asin':asin,'current_price':price,'old_price':old,'title':'LG TV 50 inch'}}
 def test_critical(self):
  c=candidate(self.report());self.assertIsNotNone(c);self.assertFalse(c['publication_allowed']);self.assertEqual(c['status'],'UNVERIFIED_REFERENCE')
 def test_book_block(self):self.assertIsNone(candidate(self.report(asin='0345520378')))
 def test_not_extreme(self):self.assertIsNone(candidate(self.report(old='2500')))
 def test_missing_reference(self):self.assertIsNone(candidate(self.report(old=None)))
 def test_negative(self):self.assertIsNone(candidate(self.report(price='-1')))
 def test_mismatch(self):
  r=self.report();r['observation']['page_asin']='B000000000';self.assertIsNone(candidate(r))
 def test_stage(self):
  with TemporaryDirectory() as d:
   p=stage(self.report(),d);self.assertTrue(p.is_file());self.assertIn('UNVERIFIED_REFERENCE',p.read_text())
if __name__=='__main__':unittest.main()
