import unittest
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import json

from planner_openapi import plan_openapi


DATE = "2026-10-26"
STOCK = {"ONT": 0, "ROUTER": 1, "STB": 0}


def at(clock):
    return f"{DATE}T{clock}+05:00"


def sample():
    center = {"service_center_id": "SC-01", "name": "Север", "address": "СЦ", "lat": 56.9, "lon": 60.6,
              "opening_hours": {"open": "08:00", "close": "18:00"}, "restock_duration_min": 15}
    installer = {"staff_id": "ST-001", "service_center_id": "SC-01", "profiles": ["INSTALL"],
                 "technologies": ["PON"], "height_permit": False, "equipment_start": STOCK,
                 "equipment_capacity": {**STOCK, "ROUTER": 3},
                 "shift": {"start": "09:00", "end": "18:00", "break_duration_min": 60,
                           "break_window": {"from": "12:00", "to": "15:00"}}}
    points = ["SC-01", "B-00001", "B-00002"]
    buildings = [{"building_id": point, "address": point, "lat": 56.9, "lon": 60.6,
                  "building_type": "MKD", "overhead_line": False} for point in points[1:]]
    reference = {"service_centers": [center], "staff": [installer],
                 "access_nodes": [{"access_node_id": "AN-0001", "node_type": "OLT", "technology": "PON",
                                   "name": "Узел", "address": "Узел", "lat": 56.9, "lon": 60.6,
                                   "buildings": buildings}],
                 "work_types": [{"code": "INST_PON_MKD", "name": "Установка", "profiles": ["INSTALL"],
                                 "duration_min": 45, "max_start_delay_min": 10,
                                 "deadline_kind": "WORKING_DAYS", "deadline_value": 3,
                                 "repeat_deadline_value": None, "pgp_relevant": False}]}
    durations = [[0, 601, 480], [501, 0, 600], [540, 720, 0]]
    matrix = {"matrix_id": "test-v1", "points": points, "durations_sec": durations,
              "distances_m": [[0, 2100, 1800], [1900, 0, 2000], [1850, 1900, 0]]}
    orders = []
    for index, clock in enumerate(("09", "11", "14"), 1):
        building = buildings[0 if index == 1 else 1]
        orders.append({
            "order_id": f"ORD-20261026-{index:04d}", "work_type_code": "INST_PON_MKD",
            "technology": "PON", "access_node_id": "AN-0001", "is_repeat": False,
            "requires_height": index == 3, "registered_at": at("08:00:00"), "required_equipment": STOCK,
            "slot": {"start": at(f"{clock}:10:00"), "end": at(f"{int(clock) + 2:02}:10:00")},
            "latest_start": at(f"{clock}:20:00"), "deadline": at("17:00:00"),
            **{key: building[key] for key in ("building_id", "address", "lat", "lon", "building_type")},
        })
    return reference, matrix, {"date": DATE, "now": at("08:30:00"), "orders": orders}


class OpenApiPlannerTest(unittest.TestCase):
    def test_published_example_matches_planner(self):
        path = Path(__file__).resolve().parents[1] / "docs/examples/planner-openapi.json"
        example = json.loads(path.read_text(encoding="utf-8"))
        args = [example[key] for key in ("reference", "matrix", "day")]
        initial = plan_openapi(*args)
        self.assertEqual(initial, example["initial_plan"])
        self.assertEqual(plan_openapi(*args, previous=initial, event=example["event"]), example["updated_plan"])

    def test_initial_plan_uses_matrix_and_refills(self):
        reference, matrix, day = sample()
        result = plan_openapi(reference, matrix, day)
        stops = result["routes"][0]["stops"]
        self.assertEqual([stop["type"] for stop in stops],
                         ["DEPOT_START", "VISIT", "RESTOCK", "VISIT", "BREAK", "DEPOT_END"])
        self.assertEqual(stops[1]["arrival"], at("09:10:01"))
        self.assertEqual(stops[3]["arrival"], at("10:26:22"))
        self.assertEqual(stops[3]["start"], at("11:10:00"))
        self.assertEqual(stops[4]["location_id"], stops[3]["location_id"])
        self.assertEqual(stops[4]["start"], at("12:00:00"))
        self.assertEqual(result["unassigned"][0]["reason_code"], "NO_QUALIFIED_STAFF")
        self.assertEqual(len({stop["order_id"] for stop in stops if stop["type"] == "VISIT"}) + len(result["unassigned"]), 3)

    def test_delay_freezes_started_visit_and_flags_next_order(self):
        reference, matrix, day = sample()
        initial = plan_openapi(reference, matrix, day)
        original = deepcopy(initial)
        first, second = day["orders"][:2]
        event = {"type": "VISIT_DELAYED", "event_id": "EV-001", "timestamp": at("09:35:00"),
                 "staff_id": "ST-001", "order_id": first["order_id"], "expected_end": at("11:10:00")}
        result = plan_openapi(reference, matrix, day, previous=initial, event=event)
        self.assertEqual(initial, original)
        self.assertEqual(result["plan_version"], 2)
        self.assertEqual(result["as_of"], event["timestamp"])
        visit = result["routes"][0]["stops"][1]
        self.assertEqual(visit, {**initial["routes"][0]["stops"][1], "end": event["expected_end"],
                                 "status": "IN_PROGRESS"})
        self.assertIn(second["order_id"], {item["order_id"] for item in result["unassigned"]})
        self.assertEqual(result["alerts"][0]["type"], "LATE_RISK")
        self.assertEqual(result["alerts"][0]["suggested_action"], "RESCHEDULE")

    def test_new_order_cannot_start_before_event_and_uses_new_leg(self):
        reference, matrix, day = sample()
        new_order = day["orders"].pop(1)
        initial = plan_openapi(reference, matrix, day)
        day["orders"].append(new_order)
        event = {"type": "NEW_ORDER", "event_id": "EV-002", "timestamp": at("10:01:00"), "order": new_order}
        result = plan_openapi(reference, matrix, day, previous=initial, event=event)
        stops = result["routes"][0]["stops"]
        restock = next(stop for stop in stops if stop["type"] == "RESTOCK")
        self.assertEqual(restock["arrival"], at("10:09:21"))
        visit = next(stop for stop in stops if stop["order_id"] == new_order["order_id"])
        self.assertGreaterEqual(visit["start"], event["timestamp"])

    def test_existing_leg_can_keep_earlier_arrival(self):
        reference, matrix, day = sample()
        initial = plan_openapi(reference, matrix, day)
        event = {"type": "TIME_TICK", "event_id": "EV-003", "timestamp": at("09:09:00")}
        result = plan_openapi(reference, matrix, day, previous=initial, event=event)
        visit = result["routes"][0]["stops"][1]
        self.assertEqual(visit["arrival"], at("09:10:01"))
        self.assertGreater(datetime.fromisoformat(visit["start"]), datetime.fromisoformat(event["timestamp"]))


if __name__ == "__main__":
    unittest.main()

class TemporaryOutageTest(unittest.TestCase):
    def test_resume_replenishes_at_home_and_preserves_input(self):
        reference,matrix,day=sample()
        previous=plan_openapi(reference,matrix,day)
        original=deepcopy(previous)
        event={'event_id':'OUT-1','type':'STAFF_UNAVAILABLE','timestamp':at('08:45:00'),'staff_id':'ST-001','until':at('10:00:00'),'reason':'VEHICLE_BREAKDOWN'}
        result=plan_openapi(reference,matrix,day,previous=previous,event=event)
        self.assertEqual(previous,original)
        route=result['routes'][0]
        reloads=[s for s in route['stops'] if s['type']=='RESTOCK' and s['location_id']=='SC-01']
        self.assertTrue(reloads)
        self.assertGreaterEqual(datetime.fromisoformat(reloads[0]['start']),datetime.fromisoformat(event['until']))
        visits=[s for s in route['stops'] if s['type']=='VISIT']
        self.assertTrue(visits)
        self.assertTrue(all(datetime.fromisoformat(s['start'])>=datetime.fromisoformat(event['until']) for s in visits))

class InterruptedVisitTest(unittest.TestCase):
    def test_unfinished_visit_is_reassigned_and_history_not_double_charged(self):
        reference,matrix,day=sample()
        original=plan_openapi(reference,matrix,day)
        visit=next(s for s in original['routes'][0]['stops'] if s['type']=='VISIT')
        replacement=deepcopy(reference['staff'][0]);replacement['staff_id']='ST-002';reference['staff'].append(replacement)
        interrupted=deepcopy(day)
        interrupted['_interrupted_visits']=[{'staff_id':'ST-001','order_id':visit['order_id'],'start':visit['start'],'interrupted_at':at('09:15:00'),'equipment_consumed':STOCK}]
        order=next(o for o in interrupted['orders'] if o['order_id']==visit['order_id'])
        order['_remaining_duration_sec']=300;order['_remaining_equipment']={'ONT':0,'ROUTER':0,'STB':0};order['latest_start']=at('10:30:00')
        event={'event_id':'OUT','type':'STAFF_UNAVAILABLE','timestamp':at('09:15:00'),'staff_id':'ST-001','reason':'ILLNESS','until':None}
        result=plan_openapi(reference,matrix,interrupted,previous=original,event=event)
        visits=[(r['staff_id'],s) for r in result['routes'] for s in r['stops'] if s.get('order_id')==visit['order_id']]
        self.assertEqual(len(visits),1)
        self.assertEqual(visits[0][0],'ST-002')
        self.assertEqual((datetime.fromisoformat(visits[0][1]['end'])-datetime.fromisoformat(visits[0][1]['start'])).total_seconds(),300)
