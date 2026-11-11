"""Realistic sample data for the Smart Healthcare case study.

State at the status date (11 Nov 2026, week 11 of 16): development is running late
and over cost, testing has found critical defects, and the hospitals' AI diagnosis
and mobile app request (CR-001: +PKR 800,000, +3 weeks) is awaiting a decision.
"""
from __future__ import annotations

from datetime import date

from .db import SCHEMA, connect
from .engine import Calendar

START = date(2026, 8, 31)
DEADLINE = date(2026, 12, 18)  # 16 weeks
STATUS = date(2026, 11, 11)
BUDGET = 5_000_000

TEAM = [
    ("Ayesha Khan", "Project Manager", 17000), ("Usman Tariq", "Backend Developer", 14000),
    ("Bilal Ahmed", "Backend Developer", 14000), ("Sara Malik", "Frontend Developer", 13000),
    ("Hamza Raza", "Frontend Developer", 13000), ("Zainab Ali", "Database Developer", 14000),
    ("Fatima Noor", "QA Engineer", 11000),
]
PM, BE1, BE2, FE1, FE2, DBA, QA = range(1, 8)

REQUIREMENTS = [  # code, title, description, priority, status, source
    ("R-001", "Patient appointment management", "Book, reschedule and cancel appointments across five hospitals.", "Must", "Approved", "Hospital management"),
    ("R-002", "Patient record management", "One shared patient record across the hospital network.", "Must", "Approved", "Medical directors"),
    ("R-003", "Laboratory reports", "Enter, approve and publish laboratory reports.", "Must", "Approved", "Laboratory heads"),
    ("R-004", "Doctor schedules", "Maintain doctor rosters, leave and clinic slots.", "Must", "Approved", "Medical directors"),
    ("R-005", "Online consultations", "Video consultation with notes and e-prescription.", "Should", "Approved", "Hospital management"),
    ("R-006", "Hospital billing", "Invoices, payments and insurance claims.", "Must", "Approved", "Finance department"),
    ("R-007", "AI preliminary diagnosis module", "Suggest a preliminary diagnosis from symptoms for doctor review.", "Should", "Proposed", "Hospital management"),
    ("R-008", "Mobile application", "Android and iOS app for patients.", "Should", "Proposed", "Hospital management"),
    ("R-009", "Audit log export", "Export access logs for compliance review.", "Could", "Proposed", "Compliance officer"),
    ("R-010", "Blockchain billing ledger", "Store invoices on a private blockchain.", "Wont", "Rejected", "IT consultant"),
]

# WBS: deliverable -> (requirement, [work packages])
WBS = [
    ("Project Management", None, ["Initiation and planning", "Monitoring and control"]),
    ("Requirements and Design", None, ["Requirements specification", "Architecture and UI design", "Database design"]),
    ("Appointments and Patient Records", "R-001", ["Appointment scheduling", "Patient records", "Appointment and patient UI", "Module testing"]),
    ("Laboratory and Doctor Schedules", "R-003", ["Laboratory reports", "Doctor schedules", "Laboratory and schedule UI"]),
    ("Online Consultations", "R-005", ["Consultation service", "Consultation UI"]),
    ("Hospital Billing", "R-006", ["Billing service", "Billing UI"]),
    ("Integration and Release", None, ["System integration", "System testing", "User acceptance", "Deployment and training", "Data migration"]),
]
WP_REQUIREMENT = {"Patient records": "R-002", "Doctor schedules": "R-004", "Laboratory and schedule UI": "R-004"}

# code, name, work package, duration, other cost, predecessors, assignments, actual start/finish offsets,
# pct, remaining days, cost factor. Offsets are working days from the project start.
ACTIVITIES = [
    ("A01", "Project charter and planning", "Initiation and planning", 5, 20000, "", {PM: 100}, 0, 4, 100, None, 1.00),
    ("A02", "Requirements across five hospitals", "Requirements specification", 8, 45000, "A01", {PM: 50, BE1: 50, QA: 50}, 5, 13, 100, None, 1.08),
    ("A03", "System architecture", "Architecture and UI design", 5, 30000, "A02", {BE1: 100, BE2: 100}, 14, 18, 100, None, 1.05),
    ("A04", "Database schema design", "Database design", 6, 25000, "A03", {DBA: 100}, 19, 25, 100, None, 1.15),
    ("A05", "UI and UX design", "Architecture and UI design", 6, 35000, "A02", {FE1: 100, FE2: 100}, 14, 19, 100, None, 1.02),
    ("A06", "Appointment scheduling API", "Appointment scheduling", 12, 30000, "A04", {BE1: 100}, 26, 39, 100, None, 1.22),
    ("A07", "Patient records API", "Patient records", 10, 30000, "A04", {BE2: 100}, 26, 35, 100, None, 1.05),
    ("A08", "Laboratory reports API", "Laboratory reports", 8, 20000, "A06", {BE1: 100}, 40, 47, 100, None, 1.04),
    ("A09", "Doctor schedule API", "Doctor schedules", 8, 15000, "A07", {BE2: 100}, 36, 43, 100, None, 1.00),
    ("A10", "Online consultation service", "Consultation service", 10, 65000, "A08", {BE1: 100}, 48, None, 40, None, 1.25),
    ("A11", "Billing and insurance service", "Billing service", 10, 40000, "A09", {BE2: 100}, 44, None, 70, None, 1.12),
    ("A12", "Appointment and patient portal UI", "Appointment and patient UI", 12, 25000, "A04, A05", {FE1: 100, FE2: 50}, 26, 37, 100, None, 1.08),
    ("A13", "Laboratory and schedule UI", "Laboratory and schedule UI", 10, 15000, "A04, A05", {FE2: 100}, 26, 35, 100, None, 1.03),
    ("A14", "Consultation UI", "Consultation UI", 8, 20000, "A12", {FE1: 100}, 38, 46, 100, None, 1.06),
    ("A15", "Billing UI", "Billing UI", 8, 15000, "A13", {FE2: 100}, 36, 45, 100, None, 1.10),
    ("A16", "Module integration across hospitals", "System integration", 8, 35000, "A10, A11, A14, A15, A21", {BE1: 100, BE2: 100, FE1: 100, FE2: 100, DBA: 50}, None, None, 0, None, 1),
    ("A17", "System and security testing", "System testing", 8, 80000, "A16", {QA: 100, BE1: 50, FE1: 50}, None, None, 0, None, 1),
    ("A18", "User acceptance at five hospitals", "User acceptance", 5, 50000, "A17", {QA: 100, PM: 50}, None, None, 0, None, 1),
    ("A19", "Deployment and staff training", "Deployment and training", 5, 100000, "A18", {BE2: 100, DBA: 100, PM: 50}, None, None, 0, None, 1),
    ("A20", "Project monitoring and control", "Monitoring and control", 74, 0, "A01", {PM: 50}, 5, None, 65, None, 1.00),
    ("A21", "Module testing: appointments and records", "Module testing", 8, 20000, "A06, A07", {QA: 100}, 40, None, 75, 4, 1.15),
    ("A22", "Data migration from five hospitals", "Data migration", 10, 40000, "A04", {DBA: 100}, 26, 37, 100, None, 1.05),
    ("A23", "Test plan and test cases", "Module testing", 8, 10000, "A02", {QA: 100}, 14, 21, 100, None, 1.00),
]

CR_ITEMS = [  # ref, requirement, name, duration, member, other cost, predecessors, successors
    ("W1", "R-007", "AI diagnosis model and API", 10, BE1, 210000, "A16", ""),
    ("W2", "R-008", "Mobile app for Android and iOS", 10, FE1, 70000, "A16", ""),
    ("W3", "R-008", "Mobile backend API", 10, BE2, 10000, "A16", ""),
    ("W4", "R-007", "AI and mobile acceptance testing", 5, QA, 45000, "W1, W2, W3", "A17"),
]

DEFECTS = [
    ("D-001", "Same appointment slot can be double-booked", "Two receptionists booking at the same time both succeed.", "Critical", "Open", BE1, "A21", 44, None, "", 45000),
    ("D-002", "Merging patient records overwrites lab history", "Merging duplicates across hospitals loses earlier lab results.", "Critical", "In Progress", BE2, "A21", 46, None, "", 60000),
    ("D-003", "Rescheduling ignores doctor leave", "Slots remain open on approved leave days.", "High", "Open", BE1, "A21", 48, None, "", 15000),
    ("D-004", "Patient search is slow above 50,000 records", "Search takes more than 8 seconds.", "Medium", "Resolved", DBA, "A07", 35, 39, "Added composite index on patient name and CNIC.", 0),
    ("D-005", "Date picker misaligned on small screens", "Calendar overlaps the form on tablets.", "Low", "Closed", FE1, "A12", 37, 41, "Responsive layout corrected.", 0),
]

CHECKS = [  # deliverable, criterion, method, result, result offset, inspector, notes
    ("Requirements and Design", "Requirements signed by all five hospitals", "Inspection", "Pass", 14, PM, "Signed copies filed."),
    ("Requirements and Design", "Database design reviewed for normalization", "Inspection", "Pass", 26, QA, "Third normal form confirmed."),
    ("Appointments and Patient Records", "No double-booking under concurrent load", "Test", "Fail", 44, QA, "Failed with 2 concurrent users. See D-001."),
    ("Appointments and Patient Records", "Patient record merge preserves history", "Test", "Fail", 46, QA, "Lab history lost. See D-002."),
    ("Appointments and Patient Records", "Code review completed", "Inspection", "Pass", 40, BE2, "Minor comments closed."),
    ("Laboratory and Doctor Schedules", "Lab report approval workflow", "Test", None, None, None, ""),
    ("Hospital Billing", "Invoice totals match tariff rules", "Test", None, None, None, ""),
    ("Integration and Release", "Patient data encrypted at rest and in transit", "Inspection", None, None, None, ""),
]

RISKS = [  # code, title, kind, deliverable, L, I, owner, status, responses
    ("RK-01", "Double-booking reaches production", "Issue", "Appointments and Patient Records", 4, 5, BE1, "Mitigating",
     [("Preventive", "Add a database unique constraint on doctor and slot", 1), ("Preventive", "Run concurrent booking tests before each release", 1), ("Corrective", "Roll back and notify affected patients", 1)]),
    ("RK-02", "Patient data lost during record merge", "Issue", "Appointments and Patient Records", 3, 5, BE2, "Mitigating",
     [("Preventive", "Make merges reversible with a history table", 1), ("Corrective", "Restore from the nightly backup", 1)]),
    ("RK-03", "Scope growth from further hospital requests", "Risk", "Project Management", 4, 4, PM, "Open",
     [("Preventive", "Route every new request through change control", 1), ("Corrective", "Defer new items to a phase 2 contract", 1)]),
    ("RK-04", "Legacy hospital data is inconsistent", "Risk", "Integration and Release", 3, 4, DBA, "Open",
     [("Preventive", "Profile each hospital's data before migration", 1), ("Corrective", "Run a manual cleansing sprint", 1), ("Corrective", "Delay go-live for all five hospitals", 0)]),
    ("RK-05", "Video service provider outage", "Risk", "Online Consultations", 2, 3, BE1, "Open",
     [("Preventive", "Contract a second video provider", 0), ("Corrective", "Fall back to voice calls", 1)]),
    ("RK-06", "Hospital staff resist the new system", "Risk", "Integration and Release", 3, 3, PM, "Open",
     [("Preventive", "Appoint a champion at each hospital", 1), ("Corrective", "Add on-site support for the first month", 1)]),
]

RACI = [("Project charter", PM, "A"), ("Project charter", BE1, "C"), ("Backend services", BE1, "R"), ("Backend services", BE2, "R"), ("Backend services", PM, "A"),
        ("Frontend and UI", FE1, "R"), ("Frontend and UI", FE2, "R"), ("Frontend and UI", PM, "A"), ("Database and migration", DBA, "R"), ("Database and migration", PM, "A"),
        ("Testing and quality", QA, "R"), ("Testing and quality", PM, "A"), ("Testing and quality", BE1, "C"), ("Change control", PM, "A"), ("Change control", QA, "I")]

MILESTONES = [("Charter approved", "A01"), ("Requirements signed off", "A02"), ("Design complete", "A04"), ("Core development complete", "A10"),
              ("Integration complete", "A16"), ("UAT sign-off", "A18"), ("Go-live", "A19")]


def seed(path):
    conn = connect(path)
    try:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        conn.execute("BEGIN")
        _load(conn)
        conn.execute("COMMIT")
    finally:
        conn.close()


def _load(c):
    cal = Calendar(START)
    iso = lambda offset: cal.date_of(offset).isoformat()
    status_offset = cal.data_offset(STATUS)

    c.execute("""INSERT INTO project(id, name, client, description, start_date, deadline, approved_budget, scope_in, scope_out,
                 status, status_date, plan_scope, plan_schedule, plan_cost, plan_quality) VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
        "Smart Healthcare Management System", "Network of Five Hospitals",
        "A single platform for appointments, laboratory reports, doctor schedules, online consultations and billing.",
        START.isoformat(), DEADLINE.isoformat(), BUDGET,
        "Patient appointments\nPatient records\nLaboratory reports\nDoctor schedules\nOnline consultations\nHospital billing\nDeployment at five hospitals",
        "Hardware procurement\nHospital network upgrades\nAny feature without an approved requirement",
        "Execution", STATUS.isoformat(),
        "Requirements are approved before entering the WBS. Any addition after the baseline goes through a change request.",
        "Critical path method on a Monday to Friday calendar, reviewed weekly against the baseline.",
        "Bottom-up estimates from team rates. Progress is tracked weekly with earned value.",
        "No critical or high defects at release. Each deliverable must pass its inspection and test checklist."))
    for t, m in [("Deliver all six core modules to five hospitals", "All approved requirements accepted at UAT"),
                 ("Finish within the approved deadline", "Go-live on or before the baselined deadline"),
                 ("Stay within the approved budget", "EAC at or below the approved budget"),
                 ("Release with no critical defects", "Zero unresolved critical defects at go-live")]:
        c.execute("INSERT INTO objectives(text, measure) VALUES (?,?)", (t, m))
    for s in [("Dr. Imran Qureshi", "Project Sponsor", "Hospital Network Board", "High"), ("Dr. Nadia Hussain", "Medical Director", "Central Hospital", "High"),
              ("Tahir Mehmood", "Finance Head", "Hospital Network", "Medium"), ("Rabia Siddiqui", "Laboratory Head", "Central Hospital", "Medium"),
              ("Kamran Javed", "IT Manager", "Hospital Network", "Medium"), ("Patients", "End Users", "Five hospitals", "Low")]:
        c.execute("INSERT INTO stakeholders(name, role, organization, influence) VALUES (?,?,?,?)", s)
    c.executemany("INSERT INTO team_members(name, role, daily_rate) VALUES (?,?,?)", TEAM)
    for area, member, raci in RACI:
        c.execute("INSERT INTO responsibilities(area, member_id, raci) VALUES (?,?,?)", (area, member, raci))

    c.execute("""INSERT INTO change_requests(id, code, title, description, justification, requested_by, raised_on, cost_impact, schedule_impact_days)
                 VALUES (1,'CR-001','AI diagnosis module and mobile application',
                 'Add an AI-based preliminary diagnosis module and a patient mobile app.',
                 'Hospital management wants faster triage and better patient access.',
                 'Hospital Management Board', ?, 800000, 15)""", (iso(40),))
    c.execute("""INSERT INTO change_requests(id, code, title, description, justification, requested_by, raised_on, cost_impact, schedule_impact_days,
                 status, decided_on, decided_by, decision_note) VALUES (2,'CR-002','Blockchain billing ledger','Store invoices on a private blockchain.',
                 'Proposed to make invoices tamper-evident.','IT consultant',?,650000,10,'Rejected',?,'Ayesha Khan',
                 'Database audit trails meet the need at far lower cost.')""", (iso(30), iso(32)))

    req_ids = {}
    for code, title, desc, priority, status, source in REQUIREMENTS:
        cr = {"R-007": 1, "R-008": 1, "R-010": 2}.get(code)
        req_ids[code] = c.execute("INSERT INTO requirements(code, title, description, priority, status, source, cr_id) VALUES (?,?,?,?,?,?,?)",
                                  (code, title, desc, priority, status, source, cr)).lastrowid

    root = c.execute("INSERT INTO wbs_items(title, kind) VALUES ('Smart Healthcare Management System','Project')").lastrowid
    deliverables, packages = {}, {}
    for i, (title, req, wps) in enumerate(WBS, 1):
        deliverables[title] = c.execute("INSERT INTO wbs_items(parent_id, title, kind, requirement_id, sort_order) VALUES (?,?,?,?,?)",
                                        (root, title, "Deliverable", req_ids.get(req), i)).lastrowid
        for j, wp in enumerate(wps, 1):
            r = WP_REQUIREMENT.get(wp, req)
            packages[wp] = c.execute("INSERT INTO wbs_items(parent_id, title, kind, requirement_id, sort_order) VALUES (?,?,?,?,?)",
                                     (deliverables[title], wp, "Work Package", req_ids.get(r), j)).lastrowid

    act_ids = {}
    for a in ACTIVITIES:
        code, name, wp, dur, other, _, _, s_off, f_off, pct, rem, _ = a
        act_ids[code] = c.execute("""INSERT INTO activities(code, wbs_id, name, duration, other_cost, pct, actual_start, actual_finish, remaining_days)
                                     VALUES (?,?,?,?,?,?,?,?,?)""",
                                  (code, packages[wp], name, dur, other, pct, iso(s_off) if s_off is not None else None,
                                   iso(f_off) if f_off is not None else None, rem)).lastrowid
    rates = {i + 1: t[2] for i, t in enumerate(TEAM)}
    for code, _, _, dur, other, preds, alloc, s_off, f_off, pct, _, factor in ACTIVITIES:
        aid = act_ids[code]
        for member, share in alloc.items():
            c.execute("INSERT INTO assignments VALUES (?,?,?)", (aid, member, share))
        for p in filter(None, (x.strip() for x in preds.split(","))):
            c.execute("INSERT INTO dependencies(pred_id, succ_id) VALUES (?,?)", (act_ids[p], aid))
        if s_off is None:
            continue
        # Weekly progress and cost entries give the S-curve a real history.
        budget = other + sum(dur * rates[m] * s / 100 for m, s in alloc.items())
        end = f_off if f_off is not None else status_offset - 1
        marks = sorted({o for o in range(s_off, end + 1) if cal.date_of(o).weekday() == 4} | {end})
        spent = 0
        for mark in marks:
            fraction = (mark - s_off + 1) / (end - s_off + 1)
            now = round(pct * fraction)
            c.execute("INSERT INTO progress_log(activity_id, log_date, pct) VALUES (?,?,?)", (aid, iso(mark), now))
            target = round(budget * now / 100 * factor, -2)
            if target > spent:
                c.execute("INSERT INTO cost_entries(activity_id, entry_date, amount, category, description) VALUES (?,?,?,'Labour','Weekly timesheet and expenses')",
                          (aid, iso(mark), int(target - spent)))
                spent = target

    for ref, req, name, dur, member, other, preds, succs in CR_ITEMS:
        c.execute("""INSERT INTO cr_work_items(cr_id, ref, requirement_id, name, duration, member_id, allocation, other_cost, predecessors, successors)
                     VALUES (1,?,?,?,?,?,100,?,?,?)""", (ref, req_ids[req], name, dur, member, other, preds, succs))
    for name, code in MILESTONES:
        c.execute("INSERT INTO milestones(name, activity_id) VALUES (?,?)", (name, act_ids[code]))
    for code, title, desc, sev, status, who, act, found, resolved, res, rework in DEFECTS:
        c.execute("""INSERT INTO defects(code, title, description, severity, status, assignee_id, activity_id, found_date, resolved_date, resolution, rework_cost)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (code, title, desc, sev, status, who, act_ids[act], iso(found), iso(resolved) if resolved else None, res, rework))
    for deliverable, criterion, method, result, offset, who, notes in CHECKS:
        item = c.execute("INSERT INTO checklist_items(wbs_id, criterion, method) VALUES (?,?,?)", (deliverables[deliverable], criterion, method)).lastrowid
        if result:
            c.execute("INSERT INTO inspection_results(item_id, result_date, result, inspector_id, notes) VALUES (?,?,?,?,?)", (item, iso(offset), result, who, notes))
    for code, title, kind, deliverable, l, i, owner, status, responses in RISKS:
        rid = c.execute("INSERT INTO risks(code, title, kind, wbs_id, likelihood, impact, owner_id, status) VALUES (?,?,?,?,?,?,?,?)",
                        (code, title, kind, deliverables[deliverable], l, i, owner, status)).lastrowid
        for t, action, feasible in responses:
            c.execute("INSERT INTO risk_responses(risk_id, type, action, feasible) VALUES (?,?,?,?)", (rid, t, action, feasible))
    for offset, status, summary in [(5, "Planning", "Charter approved and baseline set."), (26, "Execution", "Design complete, development started two days late."),
                                    (40, "Execution", "Hospital management requested AI diagnosis and a mobile app. CR-001 raised."),
                                    (46, "Execution", "Module testing found critical defects in appointments and patient records.")]:
        c.execute("INSERT INTO status_log(log_date, status, summary) VALUES (?,?,?)", (iso(offset), status, summary))

    # Original baseline v1
    total = c.execute("SELECT SUM(budget) FROM v_activity_budget").fetchone()[0]
    counts = [c.execute(q).fetchone()[0] for q in ("SELECT COUNT(*) FROM requirements WHERE status='Approved'", "SELECT COUNT(*) FROM wbs_items", "SELECT COUNT(*) FROM activities")]
    c.execute("""INSERT INTO baselines(version, created_on, reason, budget, bac, deadline, planned_finish, requirement_count, wbs_count, activity_count)
                 VALUES (1,?,'Original approved baseline',?,?,?,?,?,?,?)""", (iso(5), BUDGET, total, DEADLINE.isoformat(), DEADLINE.isoformat(), *counts))
    c.execute("INSERT INTO audit_log(action, detail) VALUES ('Sample data loaded','Case study scenario')")
