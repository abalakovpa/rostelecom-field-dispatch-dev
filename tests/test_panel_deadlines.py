import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'request-panel'))
from deadlines import calculate_deadline
class PanelDeadlineTest(unittest.TestCase):
    def test_repair_is_24_hours_from_registration_not_slot(self):
        work={'deadline_kind':'HOURS','deadline_value':24,'repeat_deadline_value':12}
        self.assertEqual(calculate_deadline(work,'2026-11-14T11:00:00+05:00','2026-11-16T13:00:00+05:00'),'2026-11-15T11:00:00+05:00')
        self.assertEqual(calculate_deadline(work,'2026-11-14T11:00:00+05:00','2026-11-16T13:00:00+05:00',True),'2026-11-14T23:00:00+05:00')
    def test_working_days_skip_weekend(self):
        self.assertEqual(calculate_deadline({'deadline_kind':'WORKING_DAYS','deadline_value':3},'2026-11-13T11:00:00+05:00','unused'),'2026-11-18T11:00:00+05:00')
    def test_slot_only(self):
        self.assertEqual(calculate_deadline({'deadline_kind':'SLOT'},'2026-11-14T11:00:00+05:00','2026-11-15T13:00:00+05:00'),'2026-11-15T13:00:00+05:00')
