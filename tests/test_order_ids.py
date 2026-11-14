import sys,unittest,re
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'request-panel'))
from order_ids import choose_order_id
class OrderIdsTest(unittest.TestCase):
    def test_collisions_and_retries_preserve_official_identifier_format(self):
        usage={'used_order_ids':[]}
        one=choose_order_id('2026-11-25','request',usage)
        usage['used_order_ids'].append(one)
        two=choose_order_id('2026-11-25','request',usage)
        self.assertNotEqual(one,two)
        self.assertRegex(one,r'^ORD-20261125-\d{4}$')
        usage['order_id']=one
        self.assertEqual(one,choose_order_id('2026-11-25','request',usage))
    def test_full_namespace_fails_without_reusing_order_ids(self):
        with self.assertRaises(ValueError):choose_order_id('2026-11-25','r',{'used_order_ids':[f'ORD-20261125-{i:04d}' for i in range(10000)]})
