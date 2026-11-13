"""Build and update the daily plan by inserting orders into simulated routes."""

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
    return sum(weights[step["order_id"]] for step in steps if step["status"] == "planned" and step.get("deadline_met"))


def _weight(order):
    return 2 if order["is_repeat"] else 1


def _qualified(worker, order, work_type):
    return _has_required_skills(worker, order, work_type["profiles"])


def _has_required_skills(worker, order, profiles):
    return (
        bool(set(worker["profiles"]).intersection(profiles))
        and order["technology"] in worker["technologies"]
        and (not order["requires_height"] or worker["height_permit"])
    )


def _public_steps(steps):
    return [{key: value for key, value in step.items() if key != "_center_id"} for step in steps]


def simulate_route(worker, orders, request):
    """Try the given visit order. Return steps and travel minutes, or a reason code."""
    snapshot = request["current_state"]
    state = next(item for item in snapshot["workers"] if item["worker_id"] == worker["id"]) if snapshot else None
    result = _simulate_route(worker, orders, request, state)
    if "steps" in result:
        result["steps"] = _public_steps(result["steps"])
    return result


def _simulate_route(worker, orders, request, state=None, *, forecast=False):
    orders = list(orders)
    work_types = {item["id"]: item for item in request["work_types"]}
    centers = {center["id"]: center for center in request["centers"]}
    home = centers[worker["center_id"]]["location_id"]
    shift_start, shift_end = _interval(worker["shift"])
    lunch_start, lunch_end = _interval(worker["lunch"])
    locked = state["locked_steps"] if state else []
    lunch_taken = any(step["type"] == "lunch" for step in locked)
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
        if not lunch_taken and departure < lunch_end and (departure >= lunch_start or departure + drive > lunch_start):
            if departure <= lunch_start:
                added.append(_step("lunch", origin, lunch_start, lunch_end, 0))
            departure = lunch_end

        start = max(departure + drive, earliest)
        if not lunch_taken and departure < lunch_start and (start >= lunch_start or start + duration > lunch_start):
            added.append(_step("lunch", location, lunch_start, lunch_end, travel))
            start = max(start, lunch_end)
            travel = 0

        end = start + duration
        if kind == "visit" and not forecast and start > latest_start:
            return None, "SLOT_UNREACHABLE"
        if end > latest_end and not (forecast and kind == "visit"):
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
        if forecast:
            return steps, None
        previous = steps[-1]
        # Keep the lunch step even when all visits finish in the morning.
        if not lunch_taken and datetime.fromisoformat(previous["end_at"]) < lunch_start:
            lunch = _step("lunch", previous["location_id"], lunch_start, lunch_end, 0)
            returning, reason = stop(lunch, "return", home, timedelta(), lunch_end, None, shift_end)
            if returning is not None:
                return steps + [lunch] + returning, None

        returning, reason = stop(previous, "return", home, timedelta(), shift_start, None, shift_end)
        if returning is None:
            return None, reason
        route = steps + returning
        if not lunch_taken and not any(step["type"] == "lunch" for step in returning) and datetime.fromisoformat(route[-1]["end_at"]) <= lunch_start:
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
        if forecast:
            return datetime.fromisoformat(steps[-1]["arrival_at"]), sum(step["travel_minutes"] for step in steps)
        weights = {order["id"]: _weight(order) for order in orders}
        return -_deadline_score(steps, weights), sum(step["travel_minutes"] for step in steps)

    for order in orders:
        if not _qualified(worker, order, work_types[order["work_type_id"]]):
            return {"reason_code": "NO_QUALIFIED_WORKER"}

    prefix = locked
    if state:
        available = max(shift_start, datetime.fromisoformat(request["as_of"]), datetime.fromisoformat(state["available_at"]))
        if locked:
            available = max(available, datetime.fromisoformat(locked[-1]["end_at"]))
        start = _step("start", state["location_id"], available, available, 0)
        if not locked and state["location_id"] == home:
            prefix = [start]
    else:
        start = _step("start", home, shift_start, shift_start, 0)
        prefix = [start]
    center_stock = {center_id: center["equipment_available"] for center_id, center in centers.items()}
    stock = state["stock"] if state else worker["stock"]
    steps, reason = extend(0, [start], stock.copy(), center_stock)
    if steps is None:
        return {"reason_code": reason}
    future = steps[1:]
    return {"steps": prefix + future, "travel_minutes": sum(step["travel_minutes"] for step in future)}


def _equipment_used(steps):
    used = Counter()
    for step in steps:
        if "_center_id" in step:
            for kind, count in step["equipment_added"].items():
                used[step["_center_id"], kind] += count
    return used


def _workload_seconds(route):
    return 60 * route["travel_minutes"] + sum(
        (datetime.fromisoformat(step["end_at"]) - datetime.fromisoformat(step["start_at"])).total_seconds()
        for step in route["steps"]
        if step["status"] == "planned" and step["type"] in {"visit", "replenishment"}
    )


def _returned_to_center(state):
    return state and any(step["type"] == "return" for step in state["locked_steps"])


def _arrival_risks(request, states, workers, orders, work_types, routes):
    if not states:
        return []

    assignments = {}
    for worker_id, route in routes.items():
        for step in route["steps"]:
            if step["type"] == "visit" and step["status"] == "planned":
                assignments[step["order_id"]] = worker_id

    prior_routes = {}
    for assignment in request["current_state"]["previous_assignments"]:
        if assignment["order_id"] in orders:
            prior_routes.setdefault(assignment["worker_id"], []).append(assignment)

    now = datetime.fromisoformat(request["as_of"])
    risks = []
    for worker_id, prior in sorted(prior_routes.items()):
        sequence = []
        for assignment in sorted(prior, key=lambda item: (datetime.fromisoformat(item["planned_arrival_at"]), item["order_id"])):
            order_id = assignment["order_id"]
            order = orders[order_id]
            sequence.append(order)
            if assignments.get(order_id) == worker_id:
                continue

            forecast = _simulate_route(workers[worker_id], sequence, request, states[worker_id], forecast=True)
            if "steps" not in forecast:
                continue
            arrival = forecast["steps"][-1]["arrival_at"]
            if datetime.fromisoformat(arrival) <= _latest_visit_start(order, work_types[order["work_type_id"]]):
                continue

            slot_start = datetime.fromisoformat(order["slot"]["start_at"])
            if order_id in assignments:
                action = {"type": "reassign", "worker_id": assignments[order_id]}
            elif slot_start - now >= timedelta(minutes=30):
                action = {"type": "propose_reschedule"}
            else:
                action = {"type": "manual_review"}
            risks.append({
                "order_id": order_id,
                "worker_id": worker_id,
                "estimated_arrival_at": arrival,
                "reason_code": "SLOT_UNREACHABLE",
                "action": action,
            })
    return risks


def plan(request):
    """Build or update a plan and return routes, unassigned orders, and risks."""
    snapshot = request["current_state"]
    states = {state["worker_id"]: state for state in snapshot["workers"]} if snapshot else {}
    locked_ids = {step["order_id"] for state in states.values() for step in state["locked_steps"] if step["type"] == "visit"}
    orders = {order["id"]: order for order in request["orders"] if order["id"] not in locked_ids}
    work_types = {item["id"]: item for item in request["work_types"]}
    weights = {order_id: _weight(order) for order_id, order in orders.items()}
    no_deadline = datetime.max.replace(tzinfo=timezone.utc)

    def order_priority(order):
        due = datetime.fromisoformat(order["due_at"]) if order["due_at"] else no_deadline
        return _latest_visit_start(order, work_types[order["work_type_id"]]), due, -_weight(order), order["id"]

    workers = sorted(request["workers"], key=lambda worker: worker["id"])
    workers_by_id = {worker["id"]: worker for worker in workers}
    if snapshot is not None and states.keys() != workers_by_id.keys():
        raise ValueError("current_state must contain a snapshot for each worker")
    visits = {worker["id"]: [] for worker in workers}
    empty_route = {"steps": [], "travel_minutes": 0}
    routes = {worker["id"]: empty_route for worker in workers}
    for worker_id, state in states.items():
        home = next(center["location_id"] for center in request["centers"]
                    if center["id"] == workers_by_id[worker_id]["center_id"])
        if not state["locked_steps"] and state["location_id"] == home:
            continue
        if _returned_to_center(state):
            routes[worker_id] = {"steps": state["locked_steps"], "travel_minutes": 0}
            continue
        route = _simulate_route(workers_by_id[worker_id], [], request, state)
        routes[worker_id] = route if "steps" in route else {"steps": state["locked_steps"], "travel_minutes": 0}
    reserved = Counter()
    unassigned = []
    reason_priority = (
        "SLOT_UNREACHABLE", "SHIFT_INFEASIBLE", "INSUFFICIENT_STOCK", "ROUTE_UNREACHABLE", "NO_QUALIFIED_WORKER",
    )

    for order in sorted(orders.values(), key=order_priority):
        best = None
        failures = set()
        total_workload = sum(_workload_seconds(route) for route in routes.values())
        for worker in workers:
            worker_id = worker["id"]
            state = states.get(worker_id)
            if _returned_to_center(state):
                if _qualified(worker, order, work_types[order["work_type_id"]]):
                    failures.add("SHIFT_INFEASIBLE")
                continue
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
                candidate = _simulate_route(worker, sequence, candidate_request, state)
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
        "risks": _arrival_risks(request, states, workers_by_id, orders, work_types, routes),
    }
