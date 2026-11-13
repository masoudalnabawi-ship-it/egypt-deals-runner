import unittest
from run_known_product import interpret_response
ASIN='B0DBHRWRKC'

class TargetTest(unittest.TestCase):
    def test_without_used_price(self):
        source={'asin':ASIN,'status':'USED_NOT_VISIBLE_ON_PRODUCT_PAGE','new_price':729.0,
                'product_page':{'http':200,'elements':[{'selector':'#productTitle','samples':['Xiaomi Redmi Buds 6 Play Black']}]},
                'product_page_used_offers':[]}
        x=interpret_response(source,ASIN)
        self.assertEqual(x['diagnosis'],'NO_USED_PRICE_VISIBLE_ON_THIS_PRODUCT_PAGE')
        self.assertEqual(x['new_price_observed'],729)
        self.assertIsNone(x['used_price_candidate'])
        self.assertFalse(x['public_posting_enabled'])

    def test_used_candidate_never_published(self):
        source={'asin':ASIN,'status':'PRODUCT_PAGE_USED_CANDIDATE_NEEDS_VERIFICATION','new_price':729,
                'lowest_used_price_candidate':200,
                'product_page':{'http':200,'elements':[{'selector':'#productTitle','samples':['Redmi Buds 6 Play']} ]},
                'product_page_used_offers':[{'condition':'USED_LIKE_NEW','price':200}]}
        x=interpret_response(source,ASIN)
        self.assertEqual(x['diagnosis'],'USED_PRICE_CANDIDATE_MANUAL_CHECK_REQUIRED')
        self.assertEqual(x['saving_percent_candidate'],72.6)
        self.assertFalse(x['used_price_verified'])
        self.assertFalse(x['checkout_verified'])

    def test_error_and_different_asin(self):
        x=interpret_response({'asin':ASIN,'status':'ERROR','product_page':{'http':429}},ASIN)
        self.assertEqual(x['diagnosis'],'PRODUCT_NOT_READABLE')
        with self.assertRaises(ValueError):
            interpret_response({'asin':'B0DYGHH7CY'},ASIN)

    def test_same_asin_unrelated_product(self):
        x=interpret_response({'asin':ASIN,'status':'USED_NOT_VISIBLE_ON_PRODUCT_PAGE','product_page':{'http':200,'elements':[{'selector':'#productTitle','samples':['Some other product']}] }},ASIN)
        self.assertEqual(x['diagnosis'],'TITLE_NOT_MATCHING_EXPECTED_REDMI')

if __name__=='__main__':unittest.main()
