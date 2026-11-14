import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'request-panel'))
from compatibility import work_fits_building
class PanelCompatibilityTest(unittest.TestCase):
    def test_work_matches_building_and_technology(self):
        building={'building_type':'MKD','technology':'FTTB','overhead_line':False}
        self.assertFalse(work_fits_building(building,{'code':'INST_PRIVATE_VLS'}))
        self.assertFalse(work_fits_building(building,{'code':'INST_PON_MKD'}))
        self.assertTrue(work_fits_building(building,{'code':'INST_FTTB_MKD'}))
        self.assertTrue(work_fits_building(building,{'code':'REPAIR'}))
