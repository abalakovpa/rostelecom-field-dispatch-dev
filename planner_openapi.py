"""Day planning using the organizers' OpenAPI payloads."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from time import monotonic

from planner import _has_required_skills


LOCAL = timezone(timedelta(hours=5))
EQUIPMENT = ("ONT", "ROUTER", "STB")
REASONS = {
    "NO_QUALIFIED_STAFF": "Нет сотрудника с подходящим профилем, технологией и допуском",
    "NO_SHIFT_TIME": "Визит не помещается в смену с учётом обеда и возврата в СЦ",
    "SLOT_UNREACHABLE": "Подходящий сотрудник не успевает начать визит в слот",
    "NO_EQUIPMENT": "Не хватает оборудования для визита с учётом доступного пополнения",
    "STAFF_UNAVAILABLE": "Прежний исполнитель недоступен, замена не найдена",
    "OTHER": "Расчёт достиг лимита времени",
}


def _seconds(value):
    return int(datetime.fromisoformat(value).timestamp())


def _iso(value):
    return datetime.fromtimestamp(value, LOCAL).isoformat()


def _local_time(date, value):
    return _seconds(f"{date}T{time.fromisoformat(value).isoformat()}+05:00")


def _equipment(counts):
    return tuple(counts.get(kind, 0) for kind in EQUIPMENT)


@dataclass(frozen=True)
class Stop:
    kind: str
    location: str
    arrival: int
    start: int
    end: int
    order: str | None = None

    @property
    def key(self):
        return self.kind, self.location, self.order


class DayPlanner:
    def __init__(self, reference, matrix, day, previous, event):
        self.date = day["date"]
        self.now = _seconds(event["timestamp"] if event else day["now"])
        self.staff = {item["staff_id"]: item for item in reference["staff"]
                      if item["staff_id"] not in day.get("absent_staff_ids", [])}
        self.centers = {
            center["service_center_id"]: (
                _local_time(self.date, center["opening_hours"]["open"]),
                _local_time(self.date, center["opening_hours"]["close"]),
                60 * center["restock_duration_min"],
            ) for center in reference["service_centers"]
        }
        self.types = {item["code"]: item for item in reference["work_types"]}
        self.orders = {item["order_id"]: item for item in day["orders"]}
        new_order_id = event["order"]["order_id"] if event and event["type"] == "NEW_ORDER" else None
        self.timing = {
            order_id: (
                max(_seconds(order["slot"]["start"]), _seconds(order["registered_at"]),
                    self.now if order_id == new_order_id else 0),
                _seconds(order["latest_start"]), _seconds(order["deadline"]),
                order.get("_remaining_duration_sec", 60 * self.types[order["work_type_code"]]["duration_min"]),
            ) for order_id, order in self.orders.items()
        }
        self.points = {point: index for index, point in enumerate(matrix["points"])}
        self.durations = matrix["durations_sec"]
        self.previous = {route["staff_id"]: route for route in (previous or {}).get("routes", [])}
        self.event = event or {}
        self.interrupted = day.get("_interrupted_visits", [])
        self.equipment_start = day.get("_equipment_start_by_staff", {})

    def travel(self, origin, destination):
        return self.durations[self.points[origin]][self.points[destination]]


class WorkerRoute:
    def __init__(self, day, staff):
        self.day = day
        self.staff = staff
        self.id = staff["staff_id"]
        self.home = staff["service_center_id"]
        shift = staff["shift"]
        self.shift_start = _local_time(day.date, shift["start"])
        self.shift_end = _local_time(day.date, shift["end"])
        self.break_first = _local_time(day.date, shift["break_window"]["from"])
        self.break_last = _local_time(day.date, shift["break_window"]["to"])
        self.break_duration = shift["break_duration_min"] * 60
        self.capacity = _equipment(staff["equipment_capacity"])
        self.stock = _equipment(day.equipment_start.get(self.id, staff["equipment_start"]))
        # Equipment already installed remains at the interrupted site.
        # Carry its expenditure with the original worker, never charge a replacement twice.
        for record in day.interrupted:
            if record["staff_id"] == self.id:
                demand = _equipment(record["equipment_consumed"])
                self.stock = tuple(a-b for a,b in zip(self.stock,demand))
        self.frozen = []
        self.old_legs = {}
        self.old_orders = []
        previous = day.previous.get(self.id, {})
        self.unavailable_from = previous.get("unavailable_from")
        self.unavailable_until = previous.get("unavailable_until")
        event = day.event
        if event.get("type") == "STAFF_UNAVAILABLE" and event["staff_id"] == self.id:
            self.unavailable_from = event["timestamp"]
            self.unavailable_until = event.get("until")
        self.resume = _seconds(self.unavailable_until) if self.unavailable_until else None

        prior = None
        for item in previous.get("stops", []):
            stop = Stop(item["type"], item["location_id"], _seconds(item["arrival"]),
                        _seconds(item["start"]), _seconds(item["end"]), item.get("order_id"))
            if prior is not None:
                leg = (prior.key, stop.key)
                self.old_legs.setdefault(leg, []).append(stop.arrival)
            prior = stop
            if any(record["staff_id"] == self.id and record["order_id"] == stop.order and record["start"] == item["start"] for record in day.interrupted):
                continue
            if stop.start >= day.now:
                if stop.order is not None:
                    self.old_orders.append(stop.order)
                continue
            if stop.order is not None and stop.order == event.get("order_id") and self.id == event.get("staff_id"):
                if event["type"] in {"VISIT_DELAYED", "ORDER_TRANSFERRED"}:
                    field = "expected_end" if event["type"] == "VISIT_DELAYED" else "actual_end"
                    stop = Stop(stop.kind, stop.location, stop.arrival, stop.start, _seconds(event[field]), stop.order)
            self.frozen.append(stop)
            if stop.kind == "RESTOCK":
                self.stock = self.capacity
            elif stop.order is not None:
                demand = _equipment(day.orders[stop.order].get("_remaining_equipment", day.orders[stop.order]["required_equipment"]))
                self.stock = tuple(available - needed for available, needed in zip(self.stock, demand))

    def qualified(self, order):
        return (not order.get("_test_staff_id") or order["_test_staff_id"] == self.id) and _has_required_skills(self.staff, order, self.day.types[order["work_type_code"]]["profiles"])

    def stop(self, previous, kind, location, earliest, duration, order=None):
        drive = self.day.travel(previous.location, location)
        key = kind, location, order
        old = self.old_legs.get((previous.key, key), [])
        # An unambiguous existing leg may already be under way at model time.
        if len(old) == 1 and kind != "RESTOCK":
            arrival = max(previous.end + drive, old[0])
        else:
            arrival = max(previous.end, self.day.now) + drive
        if self.resume is not None and self.unavailable_from and previous.start < self.resume:
            # Work resumes from the home center. Also satisfy the direct matrix leg.
            arrival = max(arrival, self.resume + self.day.travel(self.home, location))
        start = max(arrival, earliest, self.day.now)
        if kind == "DEPOT_END":
            arrival = start
        return Stop(kind, location, arrival, start, start + duration, order)

    def break_after(self, previous):
        stop = self.stop(previous, "BREAK", previous.location, self.break_first, self.break_duration)
        return stop if stop.start <= self.break_last and stop.end <= self.shift_end else None

    def add_visit(self, previous, stock, order_id, *, forecast=False):
        day = self.day
        order = day.orders[order_id]
        earliest, latest, _, duration = day.timing[order_id]
        location = order["building_id"]
        demand = _equipment(order.get("_remaining_equipment", order["required_equipment"]))
        if all(available >= needed for available, needed in zip(stock, demand)):
            options = [((), previous, stock)]
        else:
            options = []
            if all(available >= needed for available, needed in zip(self.capacity, demand)):
                for center, (opens, closes, minutes) in day.centers.items():
                    restock = self.stop(previous, "RESTOCK", center, opens, minutes)
                    if restock.end <= closes:
                        options.append(((restock,), restock, self.capacity))
        if not options:
            return (), stock, "NO_EQUIPMENT"

        candidates = [(prefix, self.stop(origin, "VISIT", location, earliest, duration, order_id), available)
                      for prefix, origin, available in options]
        def cost(item):
            prefix, visit, _ = item
            stops = (previous, *prefix, visit)
            drive = sum(day.travel(a.location, b.location) for a, b in zip(stops, stops[1:]))
            return visit.start, drive + sum(s.end-s.start for s in prefix), len(prefix)
        prefix, visit, available = min(candidates, key=cost)
        if not forecast and visit.start > latest:
            return (), stock, "NO_EQUIPMENT" if prefix else "SLOT_UNREACHABLE"
        if not forecast and visit.end > self.shift_end:
            return (), stock, "NO_SHIFT_TIME"
        return (*prefix, visit), tuple(count - used for count, used in zip(available, demand)), None

    def schedule(self, sequence, *, forecast=False):
        steps, reason = self._schedule(sequence, forecast=forecast)
        if reason and sequence and not self.unavailable_from and self.break_last >= self.day.now:
            if not any(stop.kind == "BREAK" for stop in self.frozen):
                for position in range(len(sequence) + 1):
                    steps, failure = self._schedule(sequence, forecast=forecast, break_position=position)
                    if failure is None:
                        return steps, None
        return steps, reason

    def _schedule(self, sequence, *, forecast=False, break_position=None):
        steps = self.frozen.copy()
        if self.unavailable_from and (self.resume is None or self.resume >= self.shift_end) and not forecast:
            return steps, "STAFF_UNAVAILABLE" if sequence else None
        if steps and steps[-1].kind == "DEPOT_END":
            return steps, "NO_SHIFT_TIME" if sequence else None
        if not sequence and not steps:
            return [], None
        if not steps:
            start = max(self.shift_start, self.day.now, self.resume or 0)
            if start > self.shift_end:
                return [], "NO_SHIFT_TIME"
            steps.append(Stop("DEPOT_START", self.home, start, start, start))

        stock = self.stock
        # A temporary outage ends at the home center with a replenished kit.
        # Model the replenishment explicitly so inventory replay stays auditable.
        if self.resume is not None and self.unavailable_from and self.resume < self.shift_end:
            resumed = any(stop.kind == "RESTOCK" and stop.location == self.home and stop.start >= self.resume for stop in steps)
            if not resumed:
                opens, closes, duration = self.day.centers[self.home]
                start = max(self.resume, opens, steps[-1].end + self.day.travel(steps[-1].location, self.home), self.day.now)
                if start + duration > min(closes, self.shift_end):
                    return [], "NO_SHIFT_TIME"
                steps.append(Stop("RESTOCK", self.home, start, start, start + duration))
                stock = self.capacity
        lunch = any(stop.kind == "BREAK" for stop in steps)
        for index, order_id in enumerate(sequence):
            if not lunch and break_position == index:
                pause = self.break_after(steps[-1])
                if pause is None:
                    return [], "NO_SHIFT_TIME"
                steps.append(pause)
                lunch = True
            additions, remaining, reason = self.add_visit(steps[-1], stock, order_id, forecast=forecast)
            if not lunch and break_position is None:
                pause = self.break_after(steps[-1])
                if pause is not None:
                    if not additions or additions[-1].end > self.break_last:
                        after_break, after_stock, after_reason = self.add_visit(pause, stock, order_id, forecast=forecast)
                        if not after_reason:
                            steps.append(pause)
                            lunch = True
                            additions, remaining, reason = after_break, after_stock, None
                        elif additions and not forecast:
                            return [], after_reason
            if reason:
                return [], reason
            stock = remaining
            steps.extend(additions)

        if forecast:
            return steps, None
        if not lunch and any(stop.kind == "VISIT" for stop in steps):
            pause = self.break_after(steps[-1])
            if pause is None:
                return [], "NO_SHIFT_TIME"
            steps.append(pause)
        end = self.stop(steps[-1], "DEPOT_END", self.home, self.shift_start, 0)
        if end.end > self.shift_end:
            return [], "NO_SHIFT_TIME"
        return steps + [end], None

    def score(self, steps):
        travel = sum(self.day.travel(first.location, second.location) for first, second in zip(steps, steps[1:]))
        work = sum(stop.end - stop.start for stop in steps if stop.kind in {"VISIT", "RESTOCK"})
        on_time = sum(2 if self.day.orders[stop.order]["is_repeat"] else 1
                      for stop in steps if stop.order is not None and stop.end <= self.day.timing[stop.order][2])
        return on_time, travel, travel + work

    def response(self, steps):
        return {
            "staff_id": self.id,
            "service_center_id": self.home,
            "status": "UNAVAILABLE" if self.unavailable_from and (
                not self.unavailable_until or _seconds(self.unavailable_until) > self.day.now) else "ACTIVE",
            "unavailable_from": self.unavailable_from,
            "unavailable_until": self.unavailable_until,
            "stops": [
                {"seq": index, "type": stop.kind, "location_id": stop.location, "order_id": stop.order,
                 "arrival": _iso(stop.arrival), "start": _iso(stop.start), "end": _iso(stop.end),
                 "status": "DONE" if stop.start < self.day.now and stop.end <= self.day.now else
                 "IN_PROGRESS" if stop.start < self.day.now else "PLANNED"}
                for index, stop in enumerate(steps, 1)
            ],
        }


def _late_alerts(day, workers, assignments, previous):
    alerts = list((previous or {}).get("alerts", []))
    if previous is None:
        return alerts
    existing = {(alert.get("order_id"), alert.get("staff_id"), alert["created_at"])
                for alert in alerts if alert["type"] == "LATE_RISK"}
    now = _iso(day.now)
    for worker in workers:
        sequence = []
        for order_id in worker.old_orders:
            if order_id not in assignments:
                continue
            sequence.append(order_id)
            replacement = assignments[order_id]
            if replacement == worker.id or (order_id, worker.id, now) in existing:
                continue
            forecast, _ = worker.schedule(sequence, forecast=True)
            forecast_start = forecast[-1].start if forecast else None
            latest = day.timing[order_id][1]
            if not worker.unavailable_from and (forecast_start is None or forecast_start <= latest):
                continue
            can_reschedule = _seconds(day.orders[order_id]["slot"]["start"]) - day.now >= 1800
            alerts.append({
                "alert_id": f"LATE-{previous['plan_version'] + 1}-{worker.id}-{order_id}",
                "created_at": now, "type": "LATE_RISK",
                "status": "RESOLVED" if replacement else "ACTIVE", "order_id": order_id,
                "resolved_at": now if replacement else None,
                "staff_id": worker.id, "suggested_staff_id": replacement,
                "suggested_action": "REASSIGN" if replacement else "RESCHEDULE" if can_reschedule else "NONE",
                "applied": replacement is not None,
                "forecast_start": _iso(forecast_start) if forecast_start is not None else None,
                "lateness_min": (forecast_start - latest + 59) // 60 if forecast_start and forecast_start > latest else None,
                "message": "Прежний исполнитель недоступен" if worker.unavailable_from else
                "Прежний исполнитель не успевает начать визит в слот",
            })
    return alerts


def plan_openapi(reference, matrix, day, *, previous=None, event=None, cancelled=(), pgp_groups=(), time_limit_sec=None):
    """Return a Plan. The server supplies the current order pool and owns event validation and PGP."""
    limit = monotonic() + (time_limit_sec if time_limit_sec is not None else 8 if event else 290)
    model = DayPlanner(reference, matrix, day, previous, event)
    workers = [WorkerRoute(model, model.staff[staff_id]) for staff_id in sorted(model.staff)]
    sequences = {worker.id: [] for worker in workers}
    schedules = {worker.id: worker.schedule([])[0] for worker in workers}
    scores = {worker.id: worker.score(schedules[worker.id]) for worker in workers}
    excluded = {item["order_id"] for item in cancelled}
    excluded.update(order_id for group in pgp_groups for order_id in group["order_ids"])
    excluded.update(stop.order for worker in workers for stop in worker.frozen if stop.order is not None)
    active = model.orders.keys() - excluded
    assignments = dict.fromkeys(active)
    previous_staff = {order_id: worker.id for worker in workers for order_id in worker.old_orders}
    unassigned = []

    # Retain feasible existing routes before inserting orders that need a new assignment.
    for worker in workers:
        sequence = [order_id for order_id in worker.old_orders if order_id in active]
        if not sequence or any(not worker.qualified(model.orders[order_id]) for order_id in sequence):
            continue
        steps, reason = worker.schedule(sequence)
        if reason is None:
            sequences[worker.id], schedules[worker.id], scores[worker.id] = sequence, steps, worker.score(steps)
            assignments.update(dict.fromkeys(sequence, worker.id))

    order_ids = sorted((key for key in active if assignments[key] is None), key=lambda key: (
        model.timing[key][1], not model.orders[key]["is_repeat"], model.timing[key][2], key,
    ))
    total_load = sum(score[2] for score in scores.values())
    for order_id in order_ids:
        best = None
        failures = set()
        for worker in workers:
            if monotonic() >= limit:
                failures.add("OTHER")
                break
            if not worker.qualified(model.orders[order_id]):
                continue
            old_on_time, old_travel, old_load = scores[worker.id]
            sequence = sequences[worker.id]
            for index in range(len(sequence) + 1):
                if monotonic() >= limit:
                    failures.add("OTHER")
                    break
                candidate = sequence[:index] + [order_id] + sequence[index:]
                steps, reason = worker.schedule(candidate)
                if reason:
                    failures.add(reason)
                    continue
                on_time, travel, load = worker.score(steps)
                imbalance = len(workers) * (load ** 2 - old_load ** 2) - (total_load - old_load + load) ** 2
                score = (old_on_time - on_time, worker.id != previous_staff.get(order_id, worker.id),
                         travel - old_travel, imbalance, worker.id, index)
                if best is None or score < best[0]:
                    best = score, candidate, steps, (on_time, travel, load)
        if best is None:
            reason = next((reason for reason in ("OTHER", "SLOT_UNREACHABLE", "NO_SHIFT_TIME", "NO_EQUIPMENT",
                                                "STAFF_UNAVAILABLE") if reason in failures), "NO_QUALIFIED_STAFF")
            unassigned.append({"order_id": order_id, "reason_code": reason, "reason_text": REASONS[reason],
                               "suggested_action": "RESCHEDULE" if reason == "SLOT_UNREACHABLE" else "ESCALATE"})
            continue
        score, sequence, steps, totals = best
        staff_id = score[4]
        total_load += totals[2] - scores[staff_id][2]
        sequences[staff_id], schedules[staff_id], scores[staff_id] = sequence, steps, totals
        assignments[order_id] = staff_id

    return {
        "date": model.date, "plan_version": previous["plan_version"] + 1 if previous else 1,
        "as_of": _iso(model.now), "based_on_event_id": event["event_id"] if event else None,
        "routes": [worker.response(schedules[worker.id]) for worker in workers],
        "unassigned": unassigned, "pgp_groups": list(pgp_groups), "cancelled": list(cancelled),
        "alerts": _late_alerts(model, workers, assignments, previous),
    }


