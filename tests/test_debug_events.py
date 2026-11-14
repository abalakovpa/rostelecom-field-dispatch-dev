import sys
import unittest
from copy import deepcopy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'request-panel'))
from debug_events import make_event

class DebugEventsTest(unittest.TestCase):
    def setUp(self):
        self.day={'model_now':'2026-11-18T09:00:00+05:00','plan':{'routes':[{'staff_id':'S','stops':[{'type':'VISIT','order_id':'O','start':'2026-11-18T10:00:00+05:00','end':'2026-11-18T11:00:00+05:00'}]}]}}
    def event(self,action,**kw):
        return make_event(dict(action=action,order_id='O',**kw),self.day)
    def test_start_and_finish_are_global_time_ticks_not_fake_actual_events(self):
        before=deepcopy(self.day)
        self.assertEqual(self.event('START')['timestamp'],'2026-11-18T10:00:00+05:00')
        self.assertEqual(self.event('FINISH')['type'],'TIME_TICK')
        self.assertEqual(self.event('FINISH')['timestamp'],'2026-11-18T11:00:00+05:00')
        self.assertEqual(before,self.day)
    def test_delay_requires_active_visit_and_positive_minutes(self):
        with self.assertRaises(ValueError):self.event('DELAY')
        self.day['model_now']='2026-11-18T10:00:00+05:00'
        self.assertEqual(self.event('DELAY',minutes=90)['expected_end'],'2026-11-18T12:30:00+05:00')
        with self.assertRaises(ValueError):self.event('DELAY',minutes=-1)
    def test_no_backwards_or_naive_time(self):
        for time in ['2026-11-18T08:00:00+05:00','2026-11-18T10:00:00']:
            with self.assertRaises(ValueError):self.event('TICK',time=time)
    def test_unavailability_targets_assigned_employee_and_validates_until(self):
        self.assertEqual(self.event('UNAVAILABLE')['staff_id'],'S')
        self.assertNotIn('until',self.event('UNAVAILABLE'))
        with self.assertRaises(ValueError):self.event('UNAVAILABLE',until='2026-11-18T08:00:00+05:00')
    def test_missing_visit_and_completed_visit_are_rejected(self):
        with self.assertRaises(ValueError):make_event(dict(action='START',order_id='UNKNOWN'),self.day)
        self.day['model_now']='2026-11-18T12:00:00+05:00'
        with self.assertRaises(ValueError):self.event('START')
    def test_cancellation_uses_official_event_and_unique_ids(self):
        one,two=self.event('CANCEL'),self.event('CANCEL')
        self.assertEqual(one['type'],'ORDER_CANCELLED')
        self.assertEqual(one['reason'],'CUSTOMER_REQUEST')
        self.assertNotEqual(one['event_id'],two['event_id'])
    def test_staff_can_be_unavailable_without_having_an_assigned_visit(self):
        event=make_event(dict(action='UNAVAILABLE',staff_id='OTHER'),self.day)
        self.assertEqual(event['staff_id'],'OTHER')
        self.assertEqual(event['type'],'STAFF_UNAVAILABLE')
        self.assertNotIn('order_id',event)
