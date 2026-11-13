"""Build the initial daily plan by inserting orders into simulated routes."""

from collections import Counter
from datetime import datetime, timedelta, timezone


def _interval(data):
    return datetime.fromisoformat(data["start_at"]), datetime.fromisoformat(data["end_at"])


def _step(kind, location, start, end, travel, **fields):
    return {
        "type": kind,
        "location_id": location,
        "start_at": start.isoformat(),
        "end_at": end.isoformat(),
        "travel_minutes": travel,
        "status": "planned",
        **fields,
    }


def _latest_visit_start(order, work_type):
    slot_start, slot_end = _interval(order["slot"])
    # Slots are half-open. The installation grace limit is inclusive.
    latest = slot_end - timedelta(microseconds=1)
    grace = work_type["arrival_grace_minutes"]
    if grace is not None:
        latest = min(latest, slot_start + timedelta(minutes=grace))
    return latest


def _deadline_score(steps, weights):
    return sum(weights[step["order_id"]] for step in steps if step.get("deadline_met"))


def _weight(order):
    return 2 if order["is_repeat"] else 1


def _public_steps(steps):
    return [{key: value for key, value in step.items() if key != "_center_id"} for step in steps]


def simulate_route(worker, orders, request):
    """Try the given visit order. Return steps and travel minutes, or a reason code."""
    result = _simulate_route(worker, orders, request)
    if "steps" in result:
        result["steps"] = _public_steps(result["steps"])
    return result


def _simulate_route(worker, orders, request):
    if request["current_state"] is not None:
        raise ValueError("simulate_route currently supports the initial plan only")

    orders = list(orders)
    work_types = {item["id"]: item for item in request["work_types"]}
    centers = {center["id"]: center for center in request["centers"]}
    home = centers[worker["center_id"]]["location_id"]
    shift_start, shift_end = _interval(worker["shift"])
    lunch_start, lunch_end = _interval(worker["lunch"])
    matrix = request["travel_minutes"]
    locations = {location: i for i, location in enumerate(matrix["location_ids"])}

    def stop(previous, kind, location, duration, earliest, latest_start, latest_end):
        origin = previous["location_id"]
        travel = matrix["values"][locations[origin]][locations[location]]
        if travel is None:
            return None, "ROUTE_UNREACHABLE"

        departure = datetime.fromisoformat(previous["end_at"])
        drive = timedelta(minutes=travel)
        added = []
        if departure < lunch_end and (departure >= lunch_start or departure + drive > lunch_start):
            added.append(_step("lunch", origin, lunch_start, lunch_end, 0))
            departure = lunch_end

        start = max(departure + drive, earliest)
        if departure < lunch_start and (start >= lunch_start or start + duration > lunch_start):
            added.append(_step("lunch", location, lunch_start, lunch_end, travel))
            start = max(start, lunch_end)
            travel = 0

        end = start + duration
        if kind == "visit" and start > latest_start:
            return None, "SLOT_UNREACHABLE"
        if end > latest_end:
            return None, "SHIFT_INFEASIBLE"

        added.append(_step(kind, location, start, end, travel))
        return added, None

    def visit(previous, order):
        work_type = work_types[order["work_type_id"]]
        slot_start = datetime.fromisoformat(order["slot"]["start_at"])
        latest_start = _latest_visit_start(order, work_type)
        earliest = max(slot_start, datetime.fromisoformat(order["registered_at"]))
        steps, reason = stop(
            previous, "visit", order["location_id"], timedelta(minutes=work_type["duration_minutes"]),
            earliest, latest_start, shift_end,
        )
        if steps is None:
            return None, reason
        step = steps[-1]
        due = order["due_at"]
        step.update(
            order_id=order["id"],
            arrival_at=step["start_at"],
            deadline_met=datetime.fromisoformat(step["end_at"]) <= datetime.fromisoformat(due) if due else None,
        )
        return steps, None

    def finish(steps):
        previous = steps[-1]
        # Keep the lunch step even when all visits finish in the morning.
        if datetime.fromisoformat(previous["end_at"]) < lunch_end:
            lunch = _step("lunch", previous["location_id"], lunch_start, lunch_end, 0)
            returning, reason = stop(lunch, "return", home, timedelta(), lunch_end, None, shift_end)
            if returning is not None:
                return steps + [lunch] + returning, None

        returning, reason = stop(previous, "return", home, timedelta(), shift_start, None, shift_end)
        if returning is None:
            return None, reason
        route = steps + returning
        if datetime.fromisoformat(route[-1]["end_at"]) <= lunch_start:
            route.append(_step("lunch", home, lunch_start, lunch_end, 0))
        return route, None

    def extend(index, steps, stock, center_stock):
        for position in range(index, len(orders)):
            order = orders[position]
            equipment = order["equipment"]
            missing = {kind: count - stock.get(kind, 0) for kind, count in equipment.items()
                       if count > stock.get(kind, 0)}
            if missing:
                return replenish(position, steps, stock, center_stock, missing)
            additions, reason = visit(steps[-1], order)
            if additions is None:
                return None, reason
            steps.extend(additions)
            for kind, count in equipment.items():
                stock[kind] = stock.get(kind, 0) - count
        return finish(steps)

    def replenish(index, steps, stock, center_stock, missing):
        reason = "INSUFFICIENT_STOCK"
        feasible = []
        for center_id, center in sorted(centers.items()):
            available = center_stock[center_id]
            if any(available.get(kind, 0) < count for kind, count in missing.items()):
                continue
            for opens, closes in sorted(map(_interval, center["open_intervals"])):
                additions, _ = stop(
                    steps[-1], "replenishment", center["location_id"],
                    timedelta(minutes=center["replenishment_minutes"]), opens, None, min(closes, shift_end),
                )
                if additions is None:
                    continue
                additions[-1]["equipment_added"] = missing
                additions[-1]["_center_id"] = center_id
                new_stock = stock | {kind: stock.get(kind, 0) + count for kind, count in missing.items()}
                remaining = available | {kind: available[kind] - count for kind, count in missing.items()}
                route, failure = extend(index, steps + additions, new_stock, center_stock | {center_id: remaining})
                if route is not None:
                    feasible.append(route)
                elif reason == "INSUFFICIENT_STOCK":
                    reason = failure
                break  # A later opening at the same center cannot improve this schedule.
        if not feasible:
            return None, reason
        return min(feasible, key=score), None

    def score(steps):
        weights = {order["id"]: _weight(order) for order in orders}
        return -_deadline_score(steps, weights), sum(step["travel_minutes"] for step in steps)

    for order in orders:
        allowed_profiles = work_types[order["work_type_id"]]["profiles"]
        if (not set(worker["profiles"]).intersection(allowed_profiles)
                or order["technology"] not in worker["technologies"]
                or (order["requires_height"] and not worker["height_permit"])):
            return {"reason_code": "NO_QUALIFIED_WORKER"}

    start = _step("start", home, shift_start, shift_start, 0)
    center_stock = {center_id: center["equipment_available"] for center_id, center in centers.items()}
    steps, reason = extend(0, [start], worker["stock"].copy(), center_stock)
    if steps is None:
        return {"reason_code": reason}
    return {"steps": steps, "travel_minutes": sum(step["travel_minutes"] for step in steps)}


def _equipment_used(steps):
    used = Counter()
    for step in steps:
        if step["type"] == "replenishment":
            for kind, count in step["equipment_added"].items():
                used[step["_center_id"], kind] += count
    return used


def _workload_seconds(route):
    return 60 * route["travel_minutes"] + sum(
        (datetime.fromisoformat(step["end_at"]) - datetime.fromisoformat(step["start_at"])).total_seconds()
        for step in route["steps"]
        if step["type"] in {"visit", "replenishment"}
    )


def plan(request):
    """Build an initial plan and return routes, unassigned orders, and risks."""
    if request["current_state"] is not None:
        raise ValueError("plan currently supports the initial plan only")

    work_types = {item["id"]: item for item in request["work_types"]}
    weights = {order["id"]: _weight(order) for order in request["orders"]}
    no_deadline = datetime.max.replace(tzinfo=timezone.utc)

    def order_priority(order):
        due = datetime.fromisoformat(order["due_at"]) if order["due_at"] else no_deadline
        return _latest_visit_start(order, work_types[order["work_type_id"]]), due, -_weight(order), order["id"]

    workers = sorted(request["workers"], key=lambda worker: worker["id"])
    visits = {worker["id"]: [] for worker in workers}
    empty_route = {"steps": [], "travel_minutes": 0}
    routes = {worker["id"]: empty_route for worker in workers}
    reserved = Counter()
    unassigned = []
    reason_priority = (
        "SLOT_UNREACHABLE", "SHIFT_INFEASIBLE", "INSUFFICIENT_STOCK", "ROUTE_UNREACHABLE", "NO_QUALIFIED_WORKER",
    )

    for order in sorted(request["orders"], key=order_priority):
        best = None
        failures = set()
        total_workload = sum(_workload_seconds(route) for route in routes.values())
        for worker in workers:
            worker_id = worker["id"]
            old = routes[worker_id]
            old_reservation = _equipment_used(old["steps"])
            other_reservations = reserved - old_reservation
            # A candidate may reuse its worker's reservations. Other routes keep theirs.
            available_centers = [
                {**center, "equipment_available": {
                    kind: count - other_reservations[center["id"], kind]
                    for kind, count in center["equipment_available"].items()
                }}
                for center in request["centers"]
            ]
            candidate_request = {**request, "centers": available_centers}
            old_deadline_score = _deadline_score(old["steps"], weights)
            old_workload = _workload_seconds(old)
            current_visits = visits[worker_id]
            for position in range(len(current_visits) + 1):
                sequence = current_visits[:position] + [order] + current_visits[position:]
                candidate = _simulate_route(worker, sequence, candidate_request)
                if "reason_code" in candidate:
                    failures.add(candidate["reason_code"])
                    if candidate["reason_code"] == "NO_QUALIFIED_WORKER":
                        break
                    continue

                new_workload = _workload_seconds(candidate)
                # Compare the change in the sum of squared deviations across all workers.
                new_total = total_workload - old_workload + new_workload
                imbalance = len(workers) * (new_workload ** 2 - old_workload ** 2) - new_total ** 2
                score = (
                    old_deadline_score - _deadline_score(candidate["steps"], weights),
                    candidate["travel_minutes"] - old["travel_minutes"],
                    imbalance,
                    worker_id,
                    position,
                )
                if best is None or score < best[0]:
                    best = score, sequence, candidate, other_reservations

        if best is None:
            reason = next((code for code in reason_priority if code in failures), "NO_QUALIFIED_WORKER")
            unassigned.append({"order_id": order["id"], "reason_code": reason})
            continue

        score, sequence, candidate, other_reservations = best
        worker_id = score[3]
        visits[worker_id] = sequence
        routes[worker_id] = candidate
        reserved = other_reservations + _equipment_used(candidate["steps"])

    return {
        "routes": [{"worker_id": worker_id, "steps": _public_steps(route["steps"])}
                   for worker_id, route in routes.items()],
        "unassigned": unassigned,
        "risks": [],
    }
