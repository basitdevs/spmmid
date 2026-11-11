"""Business rules for all six modules. Every write is validated and atomic."""
from __future__ import annotations

import re
from datetime import date

from . import engine
from .db import (ValidationError, audit, choice, db, decimal, integer, iso_date, next_code, one,
                 reference, rows, scalar, text, tx)
from .engine import Calendar, Link, ScheduleError, Task

PRIORITIES = ["Must", "Should", "Could", "Wont"]
SEVERITIES = ["Critical", "High", "Medium", "Low"]
DEFECT_STATUSES = ["Open", "In Progress", "Resolved", "Closed"]
PROJECT_STATUSES = ["Initiation", "Planning", "Execution", "On Hold"]
COST_CATEGORIES = ["Labour", "Software", "Hardware", "Services", "Other"]
LINK_RE = re.compile(r"^([A-Za-z]+-?\d+)(FS|SS|FF|SF)?([+-]\d+)?$", re.I)


def d(iso: str) -> date:
    return date.fromisoformat(iso)


def project():
    return one("SELECT * FROM project")


def calendar() -> Calendar:
    return Calendar(d(project()["start_date"]))


# ================================================================ schedule core
def load_tasks() -> list[Task]:
    cal = calendar()
    links: dict[int, list[Link]] = {}
    for r in rows("""SELECT x.succ_id, p.code, x.type, x.lag FROM dependencies x
                     JOIN activities p ON p.id = x.pred_id"""):
        links.setdefault(r["succ_id"], []).append(Link(r["code"], r["type"], r["lag"]))
    tasks = []
    for a in rows("SELECT * FROM activities ORDER BY id"):
        tasks.append(Task(
            code=a["code"], duration=a["duration"], preds=links.get(a["id"], []),
            actual_start=cal.offset_of(d(a["actual_start"])) if a["actual_start"] else None,
            actual_finish=cal.offset_of(d(a["actual_finish"])) + 1 if a["actual_finish"] else None,
            pct=a["pct"], remaining=a["remaining_days"]))
    return tasks


def schedule() -> dict:
    """Planned CPM network plus the forecast rolled forward from actuals."""
    p = project()
    cal = Calendar(d(p["start_date"]))
    tasks = load_tasks()
    plan, plan_finish = engine.cpm(tasks)
    data = cal.data_offset(d(p["status_date"]))
    fc, fc_finish = engine.forecast(tasks, data, plan)
    deadline_offset = cal.offset_of(d(p["deadline"])) + 1
    return {
        "project": p, "cal": cal, "tasks": tasks, "plan": plan, "plan_finish": plan_finish,
        "fc": fc, "fc_finish": fc_finish, "data": data, "deadline_offset": deadline_offset,
        "plan_finish_date": cal.finish_date(plan_finish) if tasks else cal.start,
        "fc_finish_date": cal.finish_date(fc_finish) if tasks else cal.start,
        "deadline_slip": fc_finish - deadline_offset,
    }


def bac() -> int:
    return scalar("SELECT COALESCE(SUM(budget), 0) FROM v_activity_budget")


def validate_plan():
    """The plan must stay schedulable and inside the approved budget and deadline."""
    p = project()
    try:
        s = schedule()
    except ScheduleError as exc:
        raise ValidationError(str(exc)) from None
    if s["tasks"] and s["plan_finish_date"] > d(p["deadline"]):
        raise ValidationError(
            f"This change moves the planned finish to {s['plan_finish_date']:%d %b %Y}, past the "
            f"approved deadline of {d(p['deadline']):%d %b %Y}. Raise a change request instead.")
    total = bac()
    if total > p["approved_budget"]:
        raise ValidationError(
            f"This change raises the planned cost to PKR {total:,}, above the approved budget of "
            f"PKR {p['approved_budget']:,}. Raise a change request instead.")


def parse_links(raw: str, aliases: dict[str, str] | None = None, known=None) -> list[Link]:
    """Parse text such as 'A01, A02SS+2' into dependency links."""
    links, seen = [], set()
    for token in filter(None, (t.strip() for t in (raw or "").split(","))):
        m = LINK_RE.match(token)
        if not m:
            raise ValidationError(f"'{token}' is not a valid dependency. Use a form like A01 or A02SS+2.")
        code = m.group(1).upper()
        code = (aliases or {}).get(code, code)
        if known is not None and code not in known:
            raise ValidationError(f"Dependency {code} does not exist.")
        if code in seen:
            raise ValidationError(f"Dependency {code} is listed twice.")
        seen.add(code)
        links.append(Link(code, (m.group(2) or "FS").upper(), int(m.group(3) or 0)))
    return links


def format_links(links: list[Link]) -> str:
    out = []
    for l in links:
        suffix = "" if l.type == "FS" and not l.lag else l.type
        out.append(f"{l.pred}{suffix}{f'{l.lag:+d}' if l.lag else ''}")
    return ", ".join(out)


def activity_rows(s=None) -> list[dict]:
    s = s or schedule()
    cal = s["cal"]
    data = s["data"]
    tasks = {t.code: t for t in s["tasks"]}
    budgets = {r["activity_id"]: r["budget"] for r in rows("SELECT * FROM v_activity_budget")}
    spent = {r["activity_id"]: r["ac"] for r in rows(
        "SELECT activity_id, SUM(amount) ac FROM cost_entries GROUP BY activity_id")}
    owners: dict[int, list[str]] = {}
    for r in rows("""SELECT s.activity_id, m.name, s.allocation FROM assignments s
                     JOIN team_members m ON m.id = s.member_id ORDER BY s.allocation DESC, m.id"""):
        label = r["name"] + (f" {r['allocation']}%" if r["allocation"] != 100 else "")
        owners.setdefault(r["activity_id"], []).append(label)
    out = []
    for a in rows("""SELECT a.*, w.title wp, c.code cr_code FROM activities a
                     JOIN wbs_items w ON w.id = a.wbs_id
                     LEFT JOIN change_requests c ON c.id = a.origin_cr_id ORDER BY a.id"""):
        code = a["code"]
        p, f, t = s["plan"][code], s["fc"][code], tasks[code]
        if a["actual_finish"]:
            status = "Complete" if f.slip <= 0 else "Finished late"
        elif f.slip > 0:
            status = "Delayed"
        elif a["actual_start"]:
            status = "In progress"
        else:
            status = "Not started"
        budget = budgets[a["id"]]
        ac = spent.get(a["id"], 0)
        ev = budget * a["pct"] / 100
        pv = budget * engine.planned_fraction(p.es, p.ef, data)
        out.append({
            **dict(a), "budget": budget, "ac": ac, "ev": ev, "pv": pv, "cv": ev - ac,
            "cpi": ev / ac if ac else None, "owners": ", ".join(owners.get(a["id"], [])),
            "preds": format_links(t.preds),
            "es": p.es, "ef": p.ef, "fs": f.start, "ff": f.finish,
            "planned_start": cal.date_of(p.es), "planned_finish": cal.finish_date(p.ef),
            "late_finish": cal.finish_date(p.lf), "float": p.float, "critical": p.critical,
            "forecast_start": cal.date_of(f.start), "forecast_finish": cal.finish_date(f.finish),
            "slip": f.slip, "own_slip": f.own_slip, "driver": f.driver, "state": status,
        })
    return out


def delay_report(s=None) -> list[dict]:
    """Delayed activities with the isolated effect of each root-cause delay."""
    s = s or schedule()
    out = []
    for r in activity_rows(s):
        if r["slip"] <= 0:
            continue
        impact = engine.delay_impact(s["tasks"], r["code"], r["own_slip"]) if r["own_slip"] else None
        r["impact"] = impact
        r["cause"] = "Own delay" if r["own_slip"] else f"Inherited from {r['driver']}"
        r["affected"] = sorted(impact["shifted"].items()) if impact else []
        out.append(r)
    out.sort(key=lambda r: (r["actual_finish"] is not None, -r["slip"], r["code"]))
    return out


def run_what_if(code: str, days_raw) -> dict:
    s = schedule()
    days = integer({"d": days_raw}, "d", "Delay days", 1, 200)
    if code not in {t.code for t in s["tasks"]}:
        raise ValidationError("Choose a valid activity.")
    try:
        result = engine.what_if(s["tasks"], s["data"], code, days)
    except ScheduleError as exc:
        raise ValidationError(str(exc)) from None
    cal = s["cal"]
    result.update(code=code, days=days,
                  date_before=cal.finish_date(result["finish_before"]),
                  date_after=cal.finish_date(result["finish_after"]),
                  deadline=d(s["project"]["deadline"]),
                  past_deadline=result["finish_after"] - s["deadline_offset"],
                  affected=sorted(result["shifted"].items()))
    return result


# ================================================================ activities
def _members():
    return rows("SELECT * FROM team_members ORDER BY id")


def save_activity(data, activity_id=None) -> int:
    name = text(data, "name", "Activity name", limit=200)
    wbs_id = reference(data, "wbs_id", "Work package", "wbs_items")
    if one("SELECT kind FROM wbs_items WHERE id=?", wbs_id)["kind"] != "Work Package":
        raise ValidationError("Activities can only be attached to a work package.")
    duration = integer(data, "duration", "Duration", 1, 500)
    other = integer(data, "other_cost", "Other cost", 0, 100_000_000, default=0)
    allocations = {}
    for m in _members():
        value = integer(data, f"alloc_{m['id']}", f"Allocation for {m['name']}", 0, 100, default=0)
        if value:
            allocations[m["id"]] = value
    if not allocations:
        raise ValidationError("Assign at least one team member.")
    codes = {r["code"] for r in rows("SELECT code FROM activities")}
    links = parse_links(data.get("predecessors"), known=codes)

    with tx() as c:
        if activity_id:
            a = _activity(activity_id)
            if any(l.pred == a["code"] for l in links):
                raise ValidationError("An activity cannot depend on itself.")
            if a["actual_start"]:
                old_alloc = {r["member_id"]: r["allocation"] for r in rows(
                    "SELECT * FROM assignments WHERE activity_id=?", activity_id)}
                old_links = next(t.preds for t in load_tasks() if t.code == a["code"])
                if (duration != a["duration"] or other != a["other_cost"] or allocations != old_alloc
                        or set(links) != set(old_links)):
                    raise ValidationError(
                        f"{a['code']} has started, so its plan is locked. Use Update progress "
                        "to record actuals and remaining days.")
            c.execute("UPDATE activities SET name=?, wbs_id=?, duration=?, other_cost=? WHERE id=?",
                      (name, wbs_id, duration, other, activity_id))
            code = a["code"]
        else:
            code = next_code("activities", "A", 2)
            activity_id = c.execute(
                "INSERT INTO activities(code, wbs_id, name, duration, other_cost) VALUES (?,?,?,?,?)",
                (code, wbs_id, name, duration, other)).lastrowid
        _write_network(activity_id, allocations, links)
        validate_plan()
        audit("Activity saved", f"{code} {name}")
    return activity_id


def _write_network(activity_id, allocations, links):
    c = db()
    c.execute("DELETE FROM assignments WHERE activity_id=?", (activity_id,))
    c.execute("DELETE FROM dependencies WHERE succ_id=?", (activity_id,))
    for member, alloc in allocations.items():
        c.execute("INSERT INTO assignments VALUES (?,?,?)", (activity_id, member, alloc))
    for l in links:
        pred = scalar("SELECT id FROM activities WHERE code=?", l.pred)
        if pred == activity_id:
            raise ValidationError("An activity cannot depend on itself.")
        c.execute("INSERT INTO dependencies(pred_id, succ_id, type, lag) VALUES (?,?,?,?)",
                  (pred, activity_id, l.type, l.lag))


def _activity(activity_id):
    a = one("SELECT * FROM activities WHERE id=?", activity_id)
    if not a:
        raise ValidationError("Activity not found.")
    return a


def delete_activity(activity_id):
    a = _activity(activity_id)
    checks = [
        (a["actual_start"], "it has started"),
        (a["origin_cr_id"], "it was added by an approved change request"),
        (scalar("SELECT COUNT(*) FROM cost_entries WHERE activity_id=?", activity_id), "it has costs"),
        (scalar("SELECT COUNT(*) FROM defects WHERE activity_id=?", activity_id), "it has defects"),
        (scalar("SELECT COUNT(*) FROM milestones WHERE activity_id=?", activity_id), "a milestone uses it"),
        (scalar("SELECT COUNT(*) FROM dependencies WHERE pred_id=?", activity_id), "other activities depend on it"),
    ]
    for failed, reason in checks:
        if failed:
            raise ValidationError(f"{a['code']} cannot be deleted because {reason}.")
    with tx() as c:
        c.execute("DELETE FROM dependencies WHERE succ_id=?", (activity_id,))
        c.execute("DELETE FROM activities WHERE id=?", (activity_id,))
        audit("Activity deleted", a["code"])


def record_progress(activity_id, data):
    a = _activity(activity_id)
    p = project()
    pct = integer(data, "pct", "Percent complete", 0, 100)
    log_date = iso_date(data, "log_date", "Progress date")
    start = iso_date(data, "actual_start", "Actual start", required=False) or a["actual_start"]
    remaining = integer(data, "remaining_days", "Remaining days", 1, 500, default=0) or None
    if not p["start_date"] <= log_date <= p["status_date"]:
        raise ValidationError("Progress date must be between the project start and the status date. "
                              "Move the status date in Settings first if needed.")
    last = scalar("SELECT MAX(log_date) FROM progress_log WHERE activity_id=?", activity_id)
    if last and log_date < last:
        raise ValidationError(f"Progress date cannot be before the last update ({last}).")
    if pct == 0:
        if scalar("SELECT COUNT(*) FROM cost_entries WHERE activity_id=?", activity_id):
            raise ValidationError("Progress cannot return to 0% because costs are recorded.")
        start = None
    elif not start:
        start = log_date
    if start and not p["start_date"] <= start <= log_date:
        raise ValidationError("Actual start must be between the project start and the progress date.")

    preds = rows("""SELECT p.code, p.actual_start, p.actual_finish, x.type FROM dependencies x
                    JOIN activities p ON p.id = x.pred_id WHERE x.succ_id=?""", activity_id)
    if pct > 0:
        for r in preds:
            if r["type"] == "FS" and not r["actual_finish"]:
                raise ValidationError(f"{a['code']} cannot start: predecessor {r['code']} is not finished.")
            if r["type"] == "SS" and not r["actual_start"]:
                raise ValidationError(f"{a['code']} cannot start: predecessor {r['code']} has not started.")
    finish = None
    if pct == 100:
        for r in preds:
            if r["type"] == "FF" and not r["actual_finish"]:
                raise ValidationError(f"{a['code']} cannot finish: predecessor {r['code']} is not finished.")
        blocking = rows("""SELECT code FROM defects WHERE activity_id=? AND severity IN ('Critical','High')
                           AND status IN ('Open','In Progress')""", activity_id)
        if blocking:
            raise ValidationError(f"{a['code']} cannot be completed while defects are unresolved: "
                                  + ", ".join(r["code"] for r in blocking) + ".")
        finish = a["actual_finish"] or log_date
        remaining = None
    elif a["actual_finish"]:
        started_after = scalar("""SELECT COUNT(*) FROM dependencies x JOIN activities s ON s.id = x.succ_id
                                  WHERE x.pred_id=? AND x.type='FS' AND s.actual_start IS NOT NULL""", activity_id)
        if started_after:
            raise ValidationError(f"{a['code']} cannot be reopened because a successor has started.")
    with tx() as c:
        c.execute("UPDATE activities SET pct=?, actual_start=?, actual_finish=?, remaining_days=? WHERE id=?",
                  (pct, start, finish, remaining, activity_id))
        c.execute("INSERT INTO progress_log(activity_id, log_date, pct) VALUES (?,?,?)", (activity_id, log_date, pct))
        audit("Progress recorded", f"{a['code']} {pct}% on {log_date}")


def resources(s=None) -> dict:
    """Weekly peak load per person, from the planned schedule."""
    s = s or schedule()
    weeks = (s["plan_finish"] + 4) // 5
    load: dict[int, dict[int, int]] = {}
    plan_by_id = {r["id"]: s["plan"][r["code"]] for r in rows("SELECT id, code FROM activities")}
    for r in rows("SELECT * FROM assignments"):
        t = plan_by_id[r["activity_id"]]
        days = load.setdefault(r["member_id"], {})
        for day in range(t.es, t.ef):
            days[day] = days.get(day, 0) + r["allocation"]
    people = []
    for m in _members():
        days = load.get(m["id"], {})
        cells = [max((days.get(w * 5 + i, 0) for i in range(5)), default=0) for w in range(weeks)]
        people.append({"name": m["name"], "role": m["role"], "cells": cells,
                       "person_days": sum(days.values()) / 100,
                       "over_days": sum(1 for v in days.values() if v > 100)})
    labels = [s["cal"].date_of(w * 5) for w in range(weeks)]
    return {"people": people, "weeks": labels}


def save_member(data, member_id=None):
    name = text(data, "name", "Name", limit=100)
    role = text(data, "role", "Role", limit=100)
    rate = integer(data, "daily_rate", "Daily rate", 1, 1_000_000)
    with tx() as c:
        if scalar("SELECT COUNT(*) FROM team_members WHERE name=? AND id<>?", name, member_id or 0):
            raise ValidationError(f"A team member named {name} already exists.")
        if member_id:
            old = one("SELECT * FROM team_members WHERE id=?", member_id)
            busy = scalar("""SELECT COUNT(*) FROM assignments s JOIN activities a ON a.id = s.activity_id
                             WHERE s.member_id=? AND a.actual_start IS NOT NULL""", member_id)
            if old["daily_rate"] != rate and busy:
                raise ValidationError("The rate is locked because this person works on started activities.")
            c.execute("UPDATE team_members SET name=?, role=?, daily_rate=? WHERE id=?", (name, role, rate, member_id))
        else:
            c.execute("INSERT INTO team_members(name, role, daily_rate) VALUES (?,?,?)", (name, role, rate))
        validate_plan()
        audit("Team member saved", name)


# ================================================================ integration
def save_charter(data):
    name = text(data, "name", "Project name", limit=200)
    client = text(data, "client", "Client", limit=200)
    desc = text(data, "description", "Description", required=False)
    scope_in = text(data, "scope_in", "In-scope boundary", limit=4000)
    scope_out = text(data, "scope_out", "Out-of-scope boundary", limit=4000)
    budget = integer(data, "approved_budget", "Approved budget", 1, 10_000_000_000)
    deadline = iso_date(data, "deadline", "Deadline")
    start = iso_date(data, "start_date", "Start date")
    p = project()
    if deadline < start:
        raise ValidationError("Deadline must be after the start date.")
    if scalar("SELECT COUNT(*) FROM baselines") and (
            budget != p["approved_budget"] or deadline != p["deadline"] or start != p["start_date"]):
        raise ValidationError("Budget, deadline and start date are baselined. "
                              "They can only change through an approved change request.")
    with tx() as c:
        c.execute("""UPDATE project SET name=?, client=?, description=?, scope_in=?, scope_out=?,
                     approved_budget=?, deadline=?, start_date=?""",
                  (name, client, desc, scope_in, scope_out, budget, deadline, start))
        validate_plan()
        audit("Charter updated", name)


def save_objective(data, item_id=None):
    t = text(data, "text", "Objective", limit=500)
    m = text(data, "measure", "Success measure", required=False, limit=500)
    with tx() as c:
        if item_id:
            c.execute("UPDATE objectives SET text=?, measure=? WHERE id=?", (t, m, item_id))
        else:
            c.execute("INSERT INTO objectives(text, measure) VALUES (?,?)", (t, m))


def save_stakeholder(data, item_id=None):
    vals = (text(data, "name", "Name", limit=100), text(data, "role", "Role", limit=100),
            text(data, "organization", "Organization", required=False, limit=100),
            choice(data, "influence", "Influence", ["Low", "Medium", "High"]))
    with tx() as c:
        if item_id:
            c.execute("UPDATE stakeholders SET name=?, role=?, organization=?, influence=? WHERE id=?", (*vals, item_id))
        else:
            c.execute("INSERT INTO stakeholders(name, role, organization, influence) VALUES (?,?,?,?)", vals)


def save_plan(data):
    vals = [text(data, k, label, limit=4000) for k, label in (
        ("plan_scope", "Scope plan"), ("plan_schedule", "Schedule plan"),
        ("plan_cost", "Cost plan"), ("plan_quality", "Quality plan"))]
    with tx() as c:
        c.execute("UPDATE project SET plan_scope=?, plan_schedule=?, plan_cost=?, plan_quality=?, "
                  "plan_version=plan_version+1", vals)
        audit("Project plan revised")


def add_status(data):
    p = project()
    status = choice(data, "status", "Status", PROJECT_STATUSES)
    summary = text(data, "summary", "Summary", limit=1000)
    with tx() as c:
        c.execute("UPDATE project SET status=?", (status,))
        c.execute("INSERT INTO status_log(log_date, status, summary) VALUES (?,?,?)", (p["status_date"], status, summary))
        audit("Status updated", status)


def milestones(s=None) -> list[dict]:
    s = s or schedule()
    cal = s["cal"]
    out = []
    for m in rows("""SELECT m.*, a.code, a.actual_finish FROM milestones m
                     JOIN activities a ON a.id = m.activity_id ORDER BY m.id"""):
        p, f = s["plan"][m["code"]], s["fc"][m["code"]]
        planned, forecast_date = cal.finish_date(p.ef), cal.finish_date(f.finish)
        if m["actual_finish"]:
            state = "Achieved"
        elif p.ef <= s["data"]:
            state = "Missed"
        elif f.finish > p.ef:
            state = "At risk"
        else:
            state = "On track"
        out.append({**dict(m), "planned": planned, "forecast": forecast_date, "state": state,
                    "offset": p.ef, "forecast_offset": f.finish})
    return sorted(out, key=lambda r: r["offset"])


def save_milestone(data, item_id=None):
    name = text(data, "name", "Milestone", limit=200)
    activity = reference(data, "activity_id", "Linked activity", "activities")
    with tx() as c:
        if item_id:
            c.execute("UPDATE milestones SET name=?, activity_id=? WHERE id=?", (name, activity, item_id))
        else:
            c.execute("INSERT INTO milestones(name, activity_id) VALUES (?,?)", (name, activity))


def save_responsibility(data):
    area = text(data, "area", "Responsibility area", limit=200)
    member = reference(data, "member_id", "Team member", "team_members")
    raci = choice(data, "raci", "RACI role", ["R", "A", "C", "I"])
    if raci == "A" and scalar("SELECT COUNT(*) FROM responsibilities WHERE area=? AND raci='A' AND member_id<>?", area, member):
        raise ValidationError(f"{area} already has an Accountable person. Each area can have only one.")
    with tx() as c:
        c.execute("""INSERT INTO responsibilities(area, member_id, raci) VALUES (?,?,?)
                     ON CONFLICT(area, member_id) DO UPDATE SET raci=excluded.raci""", (area, member, raci))


def closure_checks() -> list[dict]:
    open_acts = scalar("SELECT COUNT(*) FROM activities WHERE actual_finish IS NULL")
    pending = scalar("SELECT COUNT(*) FROM change_requests WHERE status='Pending'")
    defects = scalar("SELECT COUNT(*) FROM defects WHERE status IN ('Open','In Progress')")
    not_passed = scalar("""SELECT COUNT(*) FROM checklist_items c WHERE COALESCE(
        (SELECT result FROM inspection_results r WHERE r.item_id=c.id ORDER BY r.result_date DESC, r.id DESC LIMIT 1), '') <> 'Pass'""")
    return [
        {"label": "All activities finished", "ok": open_acts == 0, "detail": f"{open_acts} open"},
        {"label": "No pending change requests", "ok": pending == 0, "detail": f"{pending} pending"},
        {"label": "No unresolved defects", "ok": defects == 0, "detail": f"{defects} unresolved"},
        {"label": "All quality checks passed", "ok": not_passed == 0, "detail": f"{not_passed} not passed"},
    ]


def close_project(data):
    accepted = text(data, "accepted_by", "Accepted by", limit=200)
    lessons = text(data, "lessons", "Lessons learned", limit=4000)
    failed = [c["label"] for c in closure_checks() if not c["ok"]]
    if failed:
        raise ValidationError("The project cannot be closed yet. Failing: " + "; ".join(failed) + ".")
    p = project()
    with tx() as c:
        final_cost = scalar("SELECT COALESCE(SUM(amount),0) FROM cost_entries")
        final_finish = scalar("SELECT MAX(actual_finish) FROM activities") or p["status_date"]
        c.execute("INSERT INTO closure VALUES (1,?,?,?,?,?)", (p["status_date"], accepted, final_cost, final_finish, lessons))
        c.execute("UPDATE project SET status='Closed'")
        c.execute("INSERT INTO status_log(log_date, status, summary) VALUES (?,?,?)",
                  (p["status_date"], "Closed", f"Project closed and accepted by {accepted}."))
        audit("Project closed", accepted)


# ================================================================ scope
def save_requirement(data, req_id=None):
    priority = choice(data, "priority", "Priority", PRIORITIES)
    if req_id:
        r = one("SELECT * FROM requirements WHERE id=?", req_id)
        if not r:
            raise ValidationError("Requirement not found.")
        if r["status"] != "Proposed":
            if text(data, "title", "Title", limit=200) != r["title"] or \
                    text(data, "description", "Description", required=False) != r["description"]:
                raise ValidationError(f"{r['code']} is {r['status'].lower()}, so only its priority can change.")
    vals = (text(data, "title", "Title", limit=200), text(data, "description", "Description", required=False),
            priority, text(data, "source", "Source", required=False, limit=200))
    with tx() as c:
        if req_id:
            c.execute("UPDATE requirements SET title=?, description=?, priority=?, source=? WHERE id=?", (*vals, req_id))
        else:
            code = next_code("requirements", "R-", 3)
            req_id = c.execute("INSERT INTO requirements(code, title, description, priority, source) VALUES (?,?,?,?,?)",
                               (code, *vals)).lastrowid
        audit("Requirement saved", vals[0])
    return req_id


def decide_requirement(req_id, status):
    r = one("""SELECT r.*, c.code cr_code, c.status cr_status FROM requirements r
               LEFT JOIN change_requests c ON c.id = r.cr_id WHERE r.id=?""", req_id)
    if not r:
        raise ValidationError("Requirement not found.")
    if r["status"] != "Proposed":
        raise ValidationError(f"{r['code']} has already been {r['status'].lower()}.")
    if r["cr_id"]:
        raise ValidationError(f"{r['code']} is controlled by {r['cr_code']}. "
                              "It can only be decided through that change request.")
    with tx() as c:
        c.execute("UPDATE requirements SET status=? WHERE id=?", (status, req_id))
        audit(f"Requirement {status.lower()}", r["code"])


def traceability() -> list[dict]:
    """Requirement -> WBS -> activities -> cost -> defects."""
    s = schedule()
    acts = activity_rows(s)
    out = []
    for r in rows("""SELECT r.*, c.code cr_code FROM requirements r LEFT JOIN change_requests c ON c.id=r.cr_id
                     ORDER BY CASE r.priority WHEN 'Must' THEN 0 WHEN 'Should' THEN 1 WHEN 'Could' THEN 2 ELSE 3 END, r.code"""):
        wps = {w["id"] for w in rows("SELECT id FROM wbs_items WHERE requirement_id=? AND kind='Work Package'", r["id"])}
        mine = [a for a in acts if a["wbs_id"] in wps]
        budget = sum(a["budget"] for a in mine)
        ids = [a["id"] for a in mine]
        marks = ",".join("?" * len(ids))
        open_defects = scalar(f"SELECT COUNT(*) FROM defects WHERE status IN ('Open','In Progress') AND activity_id IN ({marks})", *ids) if ids else 0
        out.append({**dict(r), "activities": len(mine), "budget": budget, "open_defects": open_defects,
                    "progress": 100 * sum(a["ev"] for a in mine) / budget if budget else 0})
    return out


def wbs_tree() -> list[dict]:
    """Flattened WBS in tree order with generated codes and rolled-up values."""
    items = [dict(r) for r in rows("""SELECT w.*, r.code req_code FROM wbs_items w
                                      LEFT JOIN requirements r ON r.id=w.requirement_id ORDER BY w.sort_order, w.id""")]
    children: dict = {}
    for w in items:
        children.setdefault(w["parent_id"], []).append(w)
    per_wp: dict = {}
    for a in activity_rows():
        per_wp.setdefault(a["wbs_id"], []).append(a)
    flat = []

    def walk(w, code, depth):
        w.update(code=code, depth=depth)
        flat.append(w)
        acts = list(per_wp.get(w["id"], []))
        for i, child in enumerate(children.get(w["id"], []), 1):
            acts += walk(child, f"{code}.{i}", depth + 1)
        w["activities"] = [a["code"] for a in per_wp.get(w["id"], [])]
        w["budget"] = sum(a["budget"] for a in acts)
        w["progress"] = 100 * sum(a["ev"] for a in acts) / w["budget"] if w["budget"] else 0
        w["start"] = min((a["planned_start"] for a in acts), default=None)
        w["finish"] = max((a["planned_finish"] for a in acts), default=None)
        return acts

    for i, root in enumerate(children.get(None, []), 1):
        walk(root, str(i), 0)
    return flat


def _root_id():
    return scalar("SELECT id FROM wbs_items WHERE parent_id IS NULL ORDER BY id")


def save_wbs(data, item_id=None):
    title = text(data, "title", "Title", limit=200)
    kind = choice(data, "kind", "Type", ["Deliverable", "Work Package"])
    parent = reference(data, "parent_id", "Parent", "wbs_items")
    requirement = reference(data, "requirement_id", "Requirement", "requirements", required=False)
    parent_row = one("SELECT * FROM wbs_items WHERE id=?", parent)
    if kind == "Work Package" and parent_row["kind"] != "Deliverable":
        raise ValidationError("A work package must sit under a deliverable.")
    if parent_row["kind"] == "Work Package":
        raise ValidationError("A work package cannot have children.")
    if requirement and one("SELECT status FROM requirements WHERE id=?", requirement)["status"] != "Approved":
        raise ValidationError("Only approved requirements can be included in the WBS.")
    if item_id:
        node = parent
        while node:
            if node == item_id:
                raise ValidationError("A WBS item cannot be moved under itself.")
            node = scalar("SELECT parent_id FROM wbs_items WHERE id=?", node)
        if kind == "Deliverable" and scalar("SELECT COUNT(*) FROM activities WHERE wbs_id=?", item_id):
            raise ValidationError("This item has activities, so it must stay a work package.")
    with tx() as c:
        if item_id:
            c.execute("UPDATE wbs_items SET title=?, kind=?, parent_id=?, requirement_id=? WHERE id=?",
                      (title, kind, parent, requirement, item_id))
        else:
            c.execute("INSERT INTO wbs_items(title, kind, parent_id, requirement_id, sort_order) VALUES (?,?,?,?,?)",
                      (title, kind, parent, requirement, 100))
        audit("WBS saved", title)


def delete_wbs(item_id):
    w = one("SELECT * FROM wbs_items WHERE id=?", item_id)
    if not w or w["kind"] == "Project":
        raise ValidationError("This WBS item cannot be deleted.")
    for table, col, label in (("wbs_items", "parent_id", "children"), ("activities", "wbs_id", "activities"),
                              ("checklist_items", "wbs_id", "quality checks"), ("risks", "wbs_id", "risks")):
        if scalar(f"SELECT COUNT(*) FROM {table} WHERE {col}=?", item_id):
            raise ValidationError(f"This item has {label} and cannot be deleted.")
    with tx() as c:
        c.execute("DELETE FROM wbs_items WHERE id=?", (item_id,))
        audit("WBS deleted", w["title"])


def generate_wbs() -> int:
    """Create a deliverable and work package for each uncovered approved requirement."""
    missing = rows("""SELECT * FROM requirements WHERE status='Approved'
                      AND id NOT IN (SELECT requirement_id FROM wbs_items WHERE requirement_id IS NOT NULL) ORDER BY code""")
    with tx() as c:
        for r in missing:
            parent = c.execute("INSERT INTO wbs_items(parent_id, title, kind, requirement_id, sort_order) VALUES (?,?,?,?,100)",
                               (_root_id(), r["title"], "Deliverable", r["id"])).lastrowid
            c.execute("INSERT INTO wbs_items(parent_id, title, kind, requirement_id, sort_order) VALUES (?,?,?,?,1)",
                      (parent, f"{r['title']}: build", "Work Package", r["id"]))
        if missing:
            audit("WBS generated", f"{len(missing)} requirement(s)")
    return len(missing)


# ================================================================ change control
def _cr(cr_id):
    c = one("SELECT * FROM change_requests WHERE id=?", cr_id)
    if not c:
        raise ValidationError("Change request not found.")
    return c


def _pending(cr_id):
    c = _cr(cr_id)
    if c["status"] != "Pending":
        raise ValidationError(f"{c['code']} is already {c['status'].lower()}.")
    return c


def save_change(data, cr_id=None) -> int:
    p = project()
    vals = (text(data, "title", "Title", limit=200), text(data, "description", "Description", required=False),
            text(data, "justification", "Justification", limit=2000), text(data, "requested_by", "Requested by", limit=200),
            integer(data, "cost_impact", "Cost impact", 0, 1_000_000_000),
            integer(data, "schedule_impact_days", "Schedule impact", 0, 1000))
    with tx() as c:
        if cr_id:
            _pending(cr_id)
            c.execute("UPDATE change_requests SET title=?, description=?, justification=?, requested_by=?, "
                      "cost_impact=?, schedule_impact_days=? WHERE id=?", (*vals, cr_id))
        else:
            code = next_code("change_requests", "CR-", 3)
            cr_id = c.execute("""INSERT INTO change_requests(code, title, description, justification, requested_by,
                                 cost_impact, schedule_impact_days, raised_on) VALUES (?,?,?,?,?,?,?,?)""",
                              (code, *vals, p["status_date"])).lastrowid
        audit("Change request saved", vals[0])
    return cr_id


def link_requirement(cr_id, data):
    _pending(cr_id)
    req = reference(data, "requirement_id", "Requirement", "requirements")
    r = one("SELECT * FROM requirements WHERE id=?", req)
    if r["status"] != "Proposed" or r["cr_id"]:
        raise ValidationError(f"{r['code']} must be proposed and not linked to another change request.")
    with tx() as c:
        c.execute("UPDATE requirements SET cr_id=? WHERE id=?", (cr_id, req))


def unlink_requirement(cr_id, req_id):
    _pending(cr_id)
    if scalar("SELECT COUNT(*) FROM cr_work_items WHERE cr_id=? AND requirement_id=?", cr_id, req_id):
        raise ValidationError("Remove this requirement's work items first.")
    with tx() as c:
        c.execute("UPDATE requirements SET cr_id=NULL WHERE id=? AND cr_id=?", (req_id, cr_id))


def work_item_cost(item) -> int:
    rate = scalar("SELECT daily_rate FROM team_members WHERE id=?", item["member_id"])
    return round(item["duration"] * rate * item["allocation"] / 100) + item["other_cost"]


def work_items(cr_id) -> list[dict]:
    out = []
    for w in rows("""SELECT w.*, m.name member, r.code req_code FROM cr_work_items w
                     JOIN team_members m ON m.id=w.member_id JOIN requirements r ON r.id=w.requirement_id
                     WHERE w.cr_id=? ORDER BY w.id""", cr_id):
        out.append({**dict(w), "cost": work_item_cost(w)})
    return out


def save_work_item(cr_id, data, item_id=None):
    _pending(cr_id)
    requirement = reference(data, "requirement_id", "Requirement", "requirements")
    if scalar("SELECT cr_id FROM requirements WHERE id=?", requirement) != cr_id:
        raise ValidationError("The requirement must be linked to this change request.")
    preds = text(data, "predecessors", "Predecessors", required=False, limit=200)
    succs = text(data, "successors", "Successors", required=False, limit=200)
    parse_links(preds)
    parse_links(succs)
    vals = (requirement, text(data, "name", "Work item name", limit=200), integer(data, "duration", "Duration", 1, 500),
            reference(data, "member_id", "Team member", "team_members"), integer(data, "allocation", "Allocation", 1, 100),
            integer(data, "other_cost", "Other cost", 0, 1_000_000_000, default=0), preds.upper(), succs.upper())
    with tx() as c:
        if item_id:
            c.execute("""UPDATE cr_work_items SET requirement_id=?, name=?, duration=?, member_id=?, allocation=?,
                         other_cost=?, predecessors=?, successors=? WHERE id=? AND cr_id=?""", (*vals, item_id, cr_id))
        else:
            numbers = [int(r["ref"][1:]) for r in rows("SELECT ref FROM cr_work_items WHERE cr_id=?", cr_id)]
            ref = f"W{max(numbers, default=0) + 1}"
            c.execute("""INSERT INTO cr_work_items(cr_id, ref, requirement_id, name, duration, member_id, allocation,
                         other_cost, predecessors, successors) VALUES (?,?,?,?,?,?,?,?,?,?)""", (cr_id, ref, *vals))


def delete_work_item(cr_id, item_id):
    _pending(cr_id)
    with tx() as c:
        c.execute("DELETE FROM cr_work_items WHERE id=? AND cr_id=?", (item_id, cr_id))


def snapshot() -> dict:
    """Scope, schedule and budget at this moment, used for before/after comparison."""
    s = schedule()
    e = evm(s)
    p = s["project"]
    return {
        "requirements": scalar("SELECT COUNT(*) FROM requirements WHERE status='Approved'"),
        "wbs": scalar("SELECT COUNT(*) FROM wbs_items"),
        "activities": len(s["tasks"]),
        "budget": p["approved_budget"], "bac": e.bac, "reserve": p["approved_budget"] - e.bac,
        "eac": e.eac, "deadline": d(p["deadline"]), "planned_finish": s["plan_finish_date"],
        "forecast_finish": s["fc_finish_date"], "duration_weeks": s["deadline_offset"] / 5,
    }


def _apply_change(cr):
    """Apply an approved change to scope, WBS, schedule and budget."""
    c = db()
    p = project()
    items = work_items(cr["id"])
    reqs = rows("SELECT * FROM requirements WHERE cr_id=?", cr["id"])
    if not reqs:
        raise ValidationError("Link at least one requirement before approval.")
    total = sum(i["cost"] for i in items)
    if total != cr["cost_impact"]:
        raise ValidationError(f"Declared cost impact is PKR {cr['cost_impact']:,}, but the work items "
                              f"total PKR {total:,}. They must match.")
    covered = {i["requirement_id"] for i in items}
    for r in reqs:
        if r["id"] not in covered:
            raise ValidationError(f"{r['code']} has no work items in this change request.")

    c.execute("UPDATE requirements SET status='Approved' WHERE cr_id=?", (cr["id"],))
    new_deadline = engine.add_workdays(d(p["deadline"]), cr["schedule_impact_days"]).isoformat()
    c.execute("UPDATE project SET approved_budget=approved_budget+?, deadline=?, plan_version=plan_version+1",
              (cr["cost_impact"], new_deadline))

    deliverables = {}
    for r in reqs:
        deliverables[r["id"]] = c.execute(
            "INSERT INTO wbs_items(parent_id, title, kind, requirement_id, sort_order) VALUES (?,?,?,?,100)",
            (_root_id(), r["title"], "Deliverable", r["id"])).lastrowid
    aliases, ids = {}, {}
    for i in items:
        wp = c.execute("INSERT INTO wbs_items(parent_id, title, kind, requirement_id, sort_order) VALUES (?,?,?,?,1)",
                       (deliverables[i["requirement_id"]], i["name"], "Work Package", i["requirement_id"])).lastrowid
        code = next_code("activities", "A", 2)
        aliases[i["ref"]] = code
        ids[i["ref"]] = c.execute("""INSERT INTO activities(code, wbs_id, name, duration, other_cost, origin_cr_id)
                                     VALUES (?,?,?,?,?,?)""", (code, wp, i["name"], i["duration"], i["other_cost"], cr["id"])).lastrowid
    known = {r["code"] for r in rows("SELECT code FROM activities")}
    for i in items:
        _write_network(ids[i["ref"]], {i["member_id"]: i["allocation"]},
                       parse_links(i["predecessors"], aliases, known))
        for l in parse_links(i["successors"], aliases, known):
            succ = one("SELECT * FROM activities WHERE code=?", l.pred)
            if succ["actual_start"]:
                raise ValidationError(f"Successor {succ['code']} has already started.")
            c.execute("INSERT INTO dependencies(pred_id, succ_id, type, lag) VALUES (?,?,?,?)",
                      (ids[i["ref"]], succ["id"], l.type, l.lag))
    try:
        validate_plan()
    except ValidationError as exc:
        raise ValidationError(f"The declared impact is not enough. {exc}") from None


def write_baseline(reason, cr_id=None):
    s = schedule()
    p = s["project"]
    version = (scalar("SELECT MAX(version) FROM baselines") or 0) + 1
    db().execute("""INSERT INTO baselines(version, created_on, reason, cr_id, budget, bac, deadline, planned_finish,
                    requirement_count, wbs_count, activity_count) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                 (version, p["status_date"], reason, cr_id, p["approved_budget"], bac(), p["deadline"],
                  s["plan_finish_date"].isoformat(), scalar("SELECT COUNT(*) FROM requirements WHERE status='Approved'"),
                  scalar("SELECT COUNT(*) FROM wbs_items"), len(s["tasks"])))


def preview_change(cr_id) -> dict:
    """Run the real approval logic, capture the result, then roll it back."""
    cr = _cr(cr_id)
    before = snapshot()
    conn = db()
    conn.execute("SAVEPOINT preview")
    after, error = None, None
    try:
        _apply_change(cr)
        after = snapshot()
    except (ValidationError, ScheduleError) as exc:
        error = str(exc)
    finally:
        conn.execute("ROLLBACK TO preview")
        conn.execute("RELEASE preview")
    return {"before": before, "after": after, "error": error}


def decide_change(cr_id, data, status):
    cr = _pending(cr_id)
    decided_by = text(data, "decided_by", "Decided by", limit=200)
    note = text(data, "decision_note", "Decision note", required=(status == "Rejected"), limit=1000)
    p = project()
    with tx() as c:
        if status == "Approved":
            _apply_change(cr)
            write_baseline(f"{cr['code']}: {cr['title']}", cr_id)
            summary = (f"{cr['code']} approved: budget +PKR {cr['cost_impact']:,}, "
                       f"deadline +{cr['schedule_impact_days']} working days.")
            c.execute("INSERT INTO status_log(log_date, status, summary) VALUES (?,?,?)", (p["status_date"], p["status"], summary))
        else:
            c.execute("UPDATE requirements SET status='Rejected' WHERE cr_id=?", (cr_id,))
        c.execute("UPDATE change_requests SET status=?, decided_on=?, decided_by=?, decision_note=? WHERE id=?",
                  (status, p["status_date"], decided_by, note, cr_id))
        audit(f"Change request {status.lower()}", cr["code"])


# ================================================================ cost and EVM
def evm(s=None) -> engine.Evm:
    s = s or schedule()
    acts = activity_rows(s)
    return engine.Evm(bac=sum(a["budget"] for a in acts), pv=sum(a["pv"] for a in acts),
                      ev=sum(a["ev"] for a in acts),
                      ac=scalar("SELECT COALESCE(SUM(amount),0) FROM cost_entries"))


def performance_warnings(s=None) -> list[dict]:
    s = s or schedule()
    p = s["project"]
    limits = {k: p[k] for k in ("cpi_warn", "cpi_crit", "spi_warn", "spi_crit", "budget_warn_pct", "slip_warn_days")}
    alerts = engine.performance_alerts(evm(s), limits, p["approved_budget"], s["deadline_slip"])
    over = [a for a in activity_rows(s) if a["ac"] > a["budget"]]
    if over:
        worst = max(over, key=lambda a: a["ac"] - a["budget"])
        alerts.append({"level": "warning", "title": f"{len(over)} activities are over their budget",
                       "detail": f"Largest overrun: {worst['code']} {worst['name']}, "
                                 f"PKR {worst['ac'] - worst['budget']:,} over."})
    return sorted(alerts, key=lambda a: a["level"] != "critical")


def s_curve(s=None) -> list[dict]:
    """Weekly PV, EV and AC. EV and AC stop at the status date."""
    s = s or schedule()
    cal, data = s["cal"], s["data"]
    plan_by_code = s["plan"]
    acts = rows("SELECT a.id, a.code, b.budget FROM activities a JOIN v_activity_budget b ON b.activity_id=a.id")
    logs: dict[int, list] = {}
    for r in rows("SELECT * FROM progress_log ORDER BY log_date, id"):
        logs.setdefault(r["activity_id"], []).append((r["log_date"], r["pct"]))
    costs = rows("SELECT entry_date, amount FROM cost_entries")
    points = sorted(set(range(5, s["plan_finish"], 5)) | {s["plan_finish"], min(data, s["plan_finish"])} - {0})
    out = []
    for offset in points:
        day = cal.finish_date(offset)
        iso = day.isoformat()
        pv = sum(a["budget"] * engine.planned_fraction(plan_by_code[a["code"]].es, plan_by_code[a["code"]].ef, offset)
                 for a in acts)
        point = {"date": day.strftime("%d %b %Y"), "offset": offset, "pv": round(pv), "ev": None, "ac": None}
        if offset <= data:
            ev = 0.0
            for a in acts:
                pct = 0
                for log_date, value in logs.get(a["id"], []):
                    if log_date <= iso:
                        pct = value
                ev += a["budget"] * pct / 100
            point["ev"] = round(ev)
            point["ac"] = sum(c["amount"] for c in costs if c["entry_date"] <= iso)
        out.append(point)
    return out


def add_cost(data):
    p = project()
    activity = reference(data, "activity_id", "Activity", "activities")
    entry_date = iso_date(data, "entry_date", "Date")
    amount = integer(data, "amount", "Amount", 1, 1_000_000_000)
    category = choice(data, "category", "Category", COST_CATEGORIES)
    desc = text(data, "description", "Description", required=False, limit=300)
    a = _activity(activity)
    if not a["actual_start"]:
        raise ValidationError(f"{a['code']} has not started, so costs cannot be recorded against it.")
    if not a["actual_start"] <= entry_date <= p["status_date"]:
        raise ValidationError("Cost date must be between the activity's actual start and the status date.")
    with tx() as c:
        c.execute("INSERT INTO cost_entries(activity_id, entry_date, amount, category, description) VALUES (?,?,?,?,?)",
                  (activity, entry_date, amount, category, desc))
        audit("Cost recorded", f"{a['code']} PKR {amount:,}")


def delete_cost(entry_id):
    e = one("SELECT * FROM cost_entries WHERE id=?", entry_id)
    if e and e["defect_id"]:
        raise ValidationError("Rework costs posted from a defect cannot be deleted.")
    with tx() as c:
        c.execute("DELETE FROM cost_entries WHERE id=?", (entry_id,))
        audit("Cost deleted", str(entry_id))


# ================================================================ quality and risk
def save_defect(data, defect_id=None) -> int:
    p = project()
    title = text(data, "title", "Title", limit=200)
    desc = text(data, "description", "Description", required=False)
    severity = choice(data, "severity", "Severity", SEVERITIES)
    status = choice(data, "status", "Status", DEFECT_STATUSES)
    assignee = reference(data, "assignee_id", "Assigned to", "team_members", required=False)
    activity = reference(data, "activity_id", "Activity", "activities")
    found = iso_date(data, "found_date", "Found date")
    resolved = iso_date(data, "resolved_date", "Resolved date", required=False)
    resolution = text(data, "resolution", "Resolution", required=False)
    rework = integer(data, "rework_cost", "Rework cost", 0, 1_000_000_000, default=0)
    if found > p["status_date"]:
        raise ValidationError("Found date cannot be after the status date.")
    if status != "Open" and not assignee:
        raise ValidationError(f"A defect that is {status} must be assigned to someone.")
    done = status in ("Resolved", "Closed")
    if done:
        if not resolved or not resolution:
            raise ValidationError("A resolved defect needs a resolved date and a resolution note.")
        if not found <= resolved <= p["status_date"]:
            raise ValidationError("Resolved date must be between the found date and the status date.")
    else:
        resolved = None
    a = _activity(activity)
    with tx() as c:
        if defect_id:
            c.execute("""UPDATE defects SET title=?, description=?, severity=?, status=?, assignee_id=?, activity_id=?,
                         found_date=?, resolved_date=?, resolution=?, rework_cost=? WHERE id=?""",
                      (title, desc, severity, status, assignee, activity, found, resolved, resolution, rework, defect_id))
        else:
            code = next_code("defects", "D-", 3)
            defect_id = c.execute("""INSERT INTO defects(code, title, description, severity, status, assignee_id, activity_id,
                                     found_date, resolved_date, resolution, rework_cost) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                                  (code, title, desc, severity, status, assignee, activity, found, resolved, resolution, rework)).lastrowid
        if done and rework and a["actual_start"]:
            posted = scalar("SELECT COALESCE(SUM(amount),0) FROM cost_entries WHERE defect_id=?", defect_id)
            if rework > posted:
                c.execute("""INSERT INTO cost_entries(activity_id, entry_date, amount, category, description, defect_id)
                             VALUES (?,?,?,'Rework',?,?)""",
                          (activity, max(resolved, a["actual_start"]), rework - posted, f"Rework for defect: {title}", defect_id))
        audit("Defect saved", f"{title} [{status}]")
    return defect_id


def checklist() -> list[dict]:
    out = []
    for r in rows("""SELECT c.*, w.title deliverable,
          (SELECT result FROM inspection_results x WHERE x.item_id=c.id ORDER BY x.result_date DESC, x.id DESC LIMIT 1) result,
          (SELECT result_date FROM inspection_results x WHERE x.item_id=c.id ORDER BY x.result_date DESC, x.id DESC LIMIT 1) result_date,
          (SELECT notes FROM inspection_results x WHERE x.item_id=c.id ORDER BY x.result_date DESC, x.id DESC LIMIT 1) notes,
          (SELECT m.name FROM inspection_results x JOIN team_members m ON m.id=x.inspector_id WHERE x.item_id=c.id ORDER BY x.result_date DESC, x.id DESC LIMIT 1) inspector
          FROM checklist_items c JOIN wbs_items w ON w.id=c.wbs_id ORDER BY w.id, c.id"""):
        out.append(dict(r))
    return out


def save_check(data):
    wbs = reference(data, "wbs_id", "Deliverable", "wbs_items")
    if one("SELECT kind FROM wbs_items WHERE id=?", wbs)["kind"] != "Deliverable":
        raise ValidationError("Quality checks must be attached to a deliverable.")
    criterion = text(data, "criterion", "Criterion", limit=300)
    method = choice(data, "method", "Method", ["Inspection", "Test"])
    with tx() as c:
        c.execute("INSERT INTO checklist_items(wbs_id, criterion, method) VALUES (?,?,?)", (wbs, criterion, method))


def _deliverable_critical_defects(wbs_id) -> list[str]:
    return [r["code"] for r in rows("""SELECT f.code FROM defects f JOIN activities a ON a.id=f.activity_id
        JOIN wbs_items w ON w.id=a.wbs_id WHERE w.parent_id=? AND f.severity='Critical'
        AND f.status IN ('Open','In Progress')""", wbs_id)]


def record_inspection(item_id, data):
    p = project()
    item = one("SELECT * FROM checklist_items WHERE id=?", item_id)
    if not item:
        raise ValidationError("Checklist item not found.")
    when = iso_date(data, "result_date", "Result date")
    result = choice(data, "result", "Result", ["Pass", "Fail"])
    inspector = reference(data, "inspector_id", "Inspector", "team_members")
    notes = text(data, "notes", "Notes", required=(result == "Fail"), limit=1000)
    if when > p["status_date"]:
        raise ValidationError("Result date cannot be after the status date.")
    if result == "Pass":
        blocking = _deliverable_critical_defects(item["wbs_id"])
        if blocking:
            raise ValidationError("This deliverable cannot pass while critical defects are open: " + ", ".join(blocking) + ".")
    with tx() as c:
        c.execute("INSERT INTO inspection_results(item_id, result_date, result, inspector_id, notes) VALUES (?,?,?,?,?)",
                  (item_id, when, result, inspector, notes))
        audit("Inspection recorded", f"Check {item_id}: {result}")


def rating(score: int) -> str:
    return "High" if score >= 15 else "Medium" if score >= 8 else "Low"


def risk_list() -> list[dict]:
    out = []
    for r in rows("""SELECT r.*, w.title deliverable, m.name owner FROM risks r JOIN wbs_items w ON w.id=r.wbs_id
                     LEFT JOIN team_members m ON m.id=r.owner_id"""):
        score = r["likelihood"] * r["impact"]
        out.append({**dict(r), "score": score, "rating": rating(score)})
    out.sort(key=lambda r: (r["status"] == "Closed", -r["score"], -r["impact"], r["code"]))
    for rank, r in enumerate(out, 1):
        r["rank"] = rank
    return out


def save_risk(data, risk_id=None) -> int:
    vals = (text(data, "title", "Title", limit=200), choice(data, "kind", "Type", ["Risk", "Issue"]),
            reference(data, "wbs_id", "Deliverable", "wbs_items"), integer(data, "likelihood", "Likelihood", 1, 5),
            integer(data, "impact", "Impact", 1, 5), reference(data, "owner_id", "Owner", "team_members", required=False),
            choice(data, "status", "Status", ["Open", "Mitigating", "Closed"]))
    with tx() as c:
        if risk_id:
            c.execute("UPDATE risks SET title=?, kind=?, wbs_id=?, likelihood=?, impact=?, owner_id=?, status=? WHERE id=?", (*vals, risk_id))
        else:
            code = next_code("risks", "RK-", 2)
            risk_id = c.execute("INSERT INTO risks(code, title, kind, wbs_id, likelihood, impact, owner_id, status) VALUES (?,?,?,?,?,?,?,?)",
                                (code, *vals)).lastrowid
        audit("Risk saved", vals[0])
    return risk_id


def save_response(risk_id, data):
    if not one("SELECT 1 FROM risks WHERE id=?", risk_id):
        raise ValidationError("Risk not found.")
    vals = (choice(data, "type", "Type", ["Preventive", "Corrective"]), text(data, "action", "Action", limit=300),
            1 if data.get("feasible", "1") == "1" else 0)
    with tx() as c:
        c.execute("INSERT INTO risk_responses(risk_id, type, action, feasible) VALUES (?,?,?,?)", (risk_id, *vals))


def pdpc() -> list[dict]:
    """Goal -> deliverables -> potential problems -> countermeasures."""
    groups: dict = {}
    for r in risk_list():
        if r["status"] == "Closed":
            continue
        r["responses"] = rows("SELECT * FROM risk_responses WHERE risk_id=? ORDER BY type DESC, id", r["id"])
        groups.setdefault(r["deliverable"], []).append(r)
    return [{"deliverable": k, "risks": v} for k, v in groups.items()]


# ================================================================ settings and dashboard
def save_settings(data):
    status_date = iso_date(data, "status_date", "Status date")
    p = project()
    if status_date < p["start_date"]:
        raise ValidationError("Status date cannot be before the project start.")
    latest = scalar("""SELECT MAX(x) FROM (SELECT MAX(log_date) x FROM progress_log UNION SELECT MAX(entry_date) FROM cost_entries
                       UNION SELECT MAX(actual_finish) FROM activities UNION SELECT MAX(found_date) FROM defects)""")
    if latest and status_date < latest:
        raise ValidationError(f"Status date cannot be before recorded actuals (latest is {latest}).")
    cpi_warn, cpi_crit = decimal(data, "cpi_warn", "CPI warning", 0, 2), decimal(data, "cpi_crit", "CPI critical", 0, 2)
    spi_warn, spi_crit = decimal(data, "spi_warn", "SPI warning", 0, 2), decimal(data, "spi_crit", "SPI critical", 0, 2)
    if cpi_crit > cpi_warn or spi_crit > spi_warn:
        raise ValidationError("Critical limits must be at or below warning limits.")
    with tx() as c:
        c.execute("""UPDATE project SET status_date=?, cpi_warn=?, cpi_crit=?, spi_warn=?, spi_crit=?,
                     budget_warn_pct=?, slip_warn_days=?""",
                  (status_date, cpi_warn, cpi_crit, spi_warn, spi_crit,
                   decimal(data, "budget_warn_pct", "Budget warning", 1, 200),
                   integer(data, "slip_warn_days", "Allowed slip", 0, 200)))
        audit("Settings saved", f"Status date {status_date}")


def dashboard() -> dict:
    s = schedule()
    acts = activity_rows(s)
    e = evm(s)
    p = s["project"]
    warnings = performance_warnings(s)
    critical = rows("""SELECT f.*, a.code act, m.name assignee FROM defects f JOIN activities a ON a.id=f.activity_id
                       LEFT JOIN team_members m ON m.id=f.assignee_id
                       WHERE f.severity='Critical' AND f.status IN ('Open','In Progress') ORDER BY f.code""")
    if critical:
        warnings.append({"level": "critical", "title": f"{len(critical)} unresolved critical defect(s)",
                         "detail": "Linked activities cannot complete until they are resolved."})
    warnings.sort(key=lambda a: a["level"] != "critical")
    delayed = [a for a in delay_report(s) if not a["actual_finish"]]
    return {
        "p": p, "s": s, "evm": e, "warnings": warnings, "critical": critical, "delayed": delayed,
        "pending": rows("SELECT * FROM change_requests WHERE status='Pending' ORDER BY code"),
        "milestones": milestones(s), "curve": s_curve(s),
        "done": sum(1 for a in acts if a["actual_finish"]), "total": len(acts),
        "health": "Red" if any(w["level"] == "critical" for w in warnings) else "Amber" if warnings else "Green",
        "top_risks": [r for r in risk_list() if r["status"] != "Closed"][:5],
        "baselines": rows("SELECT * FROM baselines ORDER BY version"),
    }
