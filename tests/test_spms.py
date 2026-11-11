"""Automated test cases. Run: python tests/test_spms.py

Writes submission/Test_Report.html and submission/Test_Cases.csv with expected
and actual results for every case.
"""
import csv
import html
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from spms import create_app, engine, services as sv  # noqa: E402
from spms.db import ValidationError, db, one, scalar  # noqa: E402
from spms.engine import Calendar, Evm, Link, ScheduleError, Task  # noqa: E402
from spms.seed import seed  # noqa: E402

RESULTS = []
TMP = Path(tempfile.mkdtemp())
TEMPLATE = TMP / "template.db"
seed(TEMPLATE)
RULES = (ValidationError, ScheduleError, sqlite3.IntegrityError)
LIMITS = dict(cpi_warn=.95, cpi_crit=.85, spi_warn=.95, spi_crit=.85, budget_warn_pct=90, slip_warn_days=3)


class Base(unittest.TestCase):
    def setUp(self):
        self.path = TMP / f"{self.id()}.db"
        shutil.copy(TEMPLATE, self.path)
        self.app = create_app(self.path, testing=True)
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.client = self.app.test_client()

    def tearDown(self):
        self.ctx.pop()

    def case(self, tc, module, title, expected, actual):
        RESULTS.append((tc, module, title, str(expected), str(actual), expected == actual))
        self.assertEqual(expected, actual)

    def rejects(self, tc, module, title, action, fragment):
        try:
            action()
            actual = "Accepted with no error"
        except RULES as exc:
            actual = f"Rejected: {exc}"
        passed = fragment in actual and actual.startswith("Rejected")
        RESULTS.append((tc, module, title, f"Rejected with message containing '{fragment}'", actual, passed))
        self.assertTrue(passed, actual)

    def activity(self, code):
        return one("SELECT * FROM activities WHERE code=?", code)

    def new_activity(self, **over):
        wp = scalar("SELECT id FROM wbs_items WHERE title='Data migration'")
        return {"name": "Extra work", "wbs_id": wp, "duration": 1, "other_cost": 0, "predecessors": "A22", "alloc_6": 100, **over}

    def approve(self, cr=1):
        sv.decide_change(cr, {"decided_by": "PM", "decision_note": ""}, "Approved")


class Engine(Base):
    NET = [Task("A", 3), Task("B", 2, [Link("A")]), Task("C", 5, [Link("A")]), Task("D", 4, [Link("B"), Link("C")])]

    def test_calendar_weekend(self):
        self.case("TC-01", "Schedule", "One working day after Friday 4 Dec 2026", date(2026, 12, 7), engine.add_workdays(date(2026, 12, 4), 1))

    def test_calendar_16_weeks(self):
        cal = Calendar(date(2026, 8, 31))
        self.case("TC-02", "Schedule", "Last of 80 working days from 31 Aug 2026", date(2026, 12, 18), cal.finish_date(80))

    def test_cpm_finish(self):
        self.case("TC-03", "Schedule", "CPM finish, A3 to B2/C5 to D4", 12, engine.cpm(self.NET)[1])

    def test_cpm_critical(self):
        t, _ = engine.cpm(self.NET)
        self.case("TC-04", "Schedule", "Critical path activities", ["A", "C", "D"], [c for c in "ABCD" if t[c].critical])

    def test_cpm_float(self):
        self.case("TC-05", "Schedule", "Total float of non-critical B", 3, engine.cpm(self.NET)[0]["B"].float)

    def test_ss_lag(self):
        t, _ = engine.cpm([Task("A", 5), Task("B", 3, [Link("A", "SS", 2)])])
        self.case("TC-06", "Schedule", "SS+2 start offset", 2, t["B"].es)

    def test_ff(self):
        t, _ = engine.cpm([Task("A", 5), Task("B", 3, [Link("A", "FF", 1)])])
        self.case("TC-07", "Schedule", "FF+1 finish offset", 6, t["B"].ef)

    def test_cycle(self):
        self.rejects("TC-08", "Schedule", "Dependency loop detected", lambda: engine.cpm([Task("A", 1, [Link("B")]), Task("B", 1, [Link("A")])]), "loop")

    def test_delay_critical(self):
        r = engine.delay_impact(self.NET, "C", 2)
        self.case("TC-09", "Schedule", "2-day delay on critical C moves finish and D", (2, {"D": 2}), (r["finish_shift"], r["shifted"]))

    def test_delay_float(self):
        r = engine.delay_impact(self.NET, "B", 2)
        self.case("TC-10", "Schedule", "2-day delay on B is absorbed by float", (0, 2), (r["finish_shift"], r["absorbed"]))

    def test_forecast_propagates(self):
        tasks = [Task("A", 3, actual_start=0, actual_finish=5, pct=100), Task("B", 2, [Link("A")])]
        plan, _ = engine.cpm(tasks)
        fc, finish = engine.forecast(tasks, 5, plan)
        self.case("TC-11", "Schedule", "Late predecessor pushes forecast", (7, 2, 0), (finish, fc["B"].slip, fc["B"].own_slip))

    def test_evm(self):
        e = Evm(bac=10000, pv=5000, ev=4000, ac=5000)
        self.case("TC-12", "EVM", "CPI, SPI, CV, SV, EAC", (.8, .8, -1000, -1000, 12500), (e.cpi, e.spi, e.cv, e.sv, e.eac))

    def test_evm_zero(self):
        e = Evm(bac=1000, pv=0, ev=0, ac=0)
        self.case("TC-13", "EVM", "No division by zero before work starts", (None, None, 1000), (e.cpi, e.spi, e.eac))

    def test_planned_fraction(self):
        self.case("TC-14", "EVM", "Planned fraction before, during, after", (0, .5, 1), tuple(engine.planned_fraction(10, 20, x) for x in (5, 15, 25)))

    def test_alert_thresholds(self):
        a = engine.performance_alerts(Evm(1000, 500, 400, 500), LIMITS, 2000, 0)
        self.case("TC-15", "EVM", "CPI and SPI of 0.80 raise critical alerts", ["critical", "critical"], [x["level"] for x in a])

    def test_alert_clear(self):
        self.case("TC-16", "EVM", "Healthy project raises no alerts", [], engine.performance_alerts(Evm(1000, 500, 500, 500), LIMITS, 2000, 0))

    def test_alert_overrun(self):
        a = engine.performance_alerts(Evm(1000, 500, 450, 500), LIMITS, 1000, 5)
        self.case("TC-17", "EVM", "Overrun and deadline slip detected", True, any("overrun" in x["title"] for x in a) and any("past the deadline" in x["title"] for x in a))


class Integration(Base):
    def test_charter_required(self):
        self.rejects("TC-18", "Integration", "Charter with no name", lambda: sv.save_charter({**dict(sv.project()), "name": ""}), "Project name is required")

    def test_budget_locked(self):
        self.rejects("TC-19", "Integration", "Direct budget edit after baseline", lambda: sv.save_charter({**dict(sv.project()), "approved_budget": 9000000}), "approved change request")

    def test_closure_blocked(self):
        self.rejects("TC-20", "Integration", "Close project with open work", lambda: sv.close_project({"accepted_by": "Sponsor", "lessons": "x"}), "cannot be closed")

    def test_closure_ok_and_readonly(self):
        c = db()
        c.execute("UPDATE change_requests SET status='Rejected' WHERE status='Pending'")
        c.execute("UPDATE activities SET pct=100, actual_start=COALESCE(actual_start,'2026-11-01'), actual_finish='2026-11-10'")
        c.execute("UPDATE defects SET status='Closed', resolved_date='2026-11-10', resolution='Fixed'")
        for row in c.execute("SELECT id FROM checklist_items").fetchall():
            c.execute("INSERT INTO inspection_results(item_id, result_date, result, inspector_id) VALUES (?, '2026-11-11', 'Pass', 7)", (row[0],))
        sv.close_project({"accepted_by": "Sponsor", "lessons": "Keep change control strict."})
        response = self.client.post("/requirements/new", data={"title": "Late", "priority": "Must"})
        count = scalar("SELECT COUNT(*) FROM requirements WHERE title='Late'")
        self.case("TC-21", "Integration", "Closed project stores record and is read-only", ("Closed", 1, 302, 0),
                  (sv.project()["status"], scalar("SELECT COUNT(*) FROM closure"), response.status_code, count))

    def test_raci_single_accountable(self):
        self.rejects("TC-22", "Integration", "Second Accountable on one area", lambda: sv.save_responsibility({"area": "Change control", "member_id": 2, "raci": "A"}), "only one")


class Scope(Base):
    def test_add_requirement(self):
        rid = sv.save_requirement({"title": "SMS reminders", "priority": "Could"})
        self.case("TC-23", "Scope", "New requirement starts as Proposed", ("R-011", "Proposed"), tuple(one("SELECT code, status FROM requirements WHERE id=?", rid)))

    def test_bad_priority(self):
        self.rejects("TC-24", "Scope", "Invalid priority", lambda: sv.save_requirement({"title": "X", "priority": "Urgent"}), "Priority must be")

    def test_approve_requirement(self):
        rid = scalar("SELECT id FROM requirements WHERE code='R-009'")
        sv.decide_requirement(rid, "Approved")
        self.case("TC-25", "Scope", "Approve requirement with no change request", "Approved", scalar("SELECT status FROM requirements WHERE id=?", rid))

    def test_cr_controlled(self):
        rid = scalar("SELECT id FROM requirements WHERE code='R-007'")
        self.rejects("TC-26", "Scope", "Direct approval of AI requirement controlled by CR-001", lambda: sv.decide_requirement(rid, "Approved"), "only be decided through")

    def test_wbs_gate_service(self):
        rid = scalar("SELECT id FROM requirements WHERE code='R-007'")
        root = scalar("SELECT id FROM wbs_items WHERE kind='Project'")
        self.rejects("TC-27", "Scope", "Add unapproved requirement to WBS", lambda: sv.save_wbs({"title": "AI", "kind": "Deliverable", "parent_id": root, "requirement_id": rid}), "Only approved")

    def test_wbs_gate_database(self):
        rid = scalar("SELECT id FROM requirements WHERE code='R-008'")
        self.rejects("TC-28", "Scope", "Database trigger blocks direct SQL insert", lambda: db().execute("INSERT INTO wbs_items(parent_id,title,kind,requirement_id) VALUES (1,'X','Deliverable',?)", (rid,)), "Only approved")

    def test_generate_only_approved(self):
        rid = scalar("SELECT id FROM requirements WHERE code='R-009'")
        sv.decide_requirement(rid, "Approved")
        created = sv.generate_wbs()
        leaked = scalar("SELECT COUNT(*) FROM wbs_items w JOIN requirements r ON r.id=w.requirement_id WHERE r.status<>'Approved'")
        self.case("TC-29", "Scope", "Generate WBS adds approved only", (1, 0), (created, leaked))

    def test_wbs_codes(self):
        tree = sv.wbs_tree()
        self.case("TC-30", "Scope", "Hierarchical codes", ("1", "1.1", "1.1.1"), (tree[0]["code"], tree[1]["code"], tree[2]["code"]))

    def test_wbs_rollup(self):
        self.case("TC-31", "Scope", "WBS root budget equals total planned budget", sv.bac(), sv.wbs_tree()[0]["budget"])

    def test_wbs_has_work(self):
        wp = scalar("SELECT id FROM wbs_items WHERE title='Data migration'")
        self.rejects("TC-32", "Scope", "Delete work package with activities", lambda: sv.delete_wbs(wp), "cannot be deleted")

    def test_approved_text_locked(self):
        r = dict(one("SELECT * FROM requirements WHERE code='R-001'"))
        self.rejects("TC-33", "Scope", "Edit title of approved requirement", lambda: sv.save_requirement({**r, "title": "Changed"}, r["id"]), "only its priority")


class Change(Base):
    def test_case_study_budget(self):
        self.approve()
        self.case("TC-34", "Change control", "Budget after CR-001", 5800000, sv.project()["approved_budget"])

    def test_case_study_deadline(self):
        self.approve()
        self.case("TC-35", "Change control", "Deadline after +3 weeks", "2027-01-08", sv.project()["deadline"])

    def test_scope_updated(self):
        self.approve()
        approved = scalar("SELECT COUNT(*) FROM requirements WHERE status='Approved'")
        wbs = scalar("SELECT COUNT(*) FROM wbs_items w JOIN requirements r ON r.id=w.requirement_id WHERE r.code IN ('R-007','R-008')")
        self.case("TC-36", "Change control", "Requirements approved and WBS extended", (8, 6), (approved, wbs))

    def test_schedule_updated(self):
        self.approve()
        s = sv.schedule()
        self.case("TC-37", "Change control", "Network recalculated to 19 weeks", (27, 95, date(2027, 1, 8)), (len(s["tasks"]), s["plan_finish"], s["plan_finish_date"]))

    def test_cost_updated(self):
        before = sv.bac()
        self.approve()
        self.case("TC-38", "Change control", "Planned cost rises by exact impact", before + 800000, sv.bac())

    def test_baseline(self):
        self.approve()
        b = one("SELECT * FROM baselines WHERE version=2")
        self.case("TC-39", "Change control", "New baseline v2 recorded", (5800000, "2027-01-08", 1), (b["budget"], b["deadline"], b["cr_id"]))

    def test_preview_no_change(self):
        result = sv.preview_change(1)
        self.case("TC-40", "Change control", "Preview shows effect but changes nothing", (5800000, 5000000, 23), (result["after"]["budget"], sv.project()["approved_budget"], scalar("SELECT COUNT(*) FROM activities")))

    def test_reject(self):
        sv.decide_change(1, {"decided_by": "PM", "decision_note": "No funds"}, "Rejected")
        self.case("TC-41", "Change control", "Rejected CR leaves budget, rejects requirements", (5000000, "Rejected"), (sv.project()["approved_budget"], scalar("SELECT status FROM requirements WHERE code='R-007'")))

    def test_reject_note(self):
        self.rejects("TC-42", "Change control", "Reject with no reason", lambda: sv.decide_change(1, {"decided_by": "PM"}, "Rejected"), "Decision note is required")

    def test_double_approve(self):
        self.approve()
        self.rejects("TC-43", "Change control", "Approve the same CR twice", self.approve, "already approved")

    def test_cost_mismatch_atomic(self):
        db().execute("UPDATE change_requests SET cost_impact=700000 WHERE id=1")
        self.rejects("TC-44", "Change control", "Declared cost differs from work items", self.approve, "must match")
        self.case("TC-45", "Change control", "Failed approval rolls back all changes", (5000000, 23, "Proposed"), (sv.project()["approved_budget"], scalar("SELECT COUNT(*) FROM activities"), scalar("SELECT status FROM requirements WHERE code='R-007'")))

    def test_understated_schedule(self):
        db().execute("UPDATE change_requests SET schedule_impact_days=5 WHERE id=1")
        self.rejects("TC-46", "Change control", "Schedule impact understated", self.approve, "declared impact is not enough")

    def test_negative_cost(self):
        self.rejects("TC-47", "Change control", "Negative cost impact", lambda: sv.save_change({"title": "X", "justification": "Y", "requested_by": "Z", "cost_impact": -5, "schedule_impact_days": 0}), "at least 0")


class Schedule(Base):
    def test_add_in_float(self):
        before = scalar("SELECT COUNT(*) FROM activities")
        sv.save_activity(self.new_activity())
        self.case("TC-48", "Schedule", "Activity within float and budget is accepted", before + 1, scalar("SELECT COUNT(*) FROM activities"))

    def test_past_deadline(self):
        self.rejects("TC-49", "Schedule", "New activity pushes plan past deadline", lambda: sv.save_activity(self.new_activity(duration=100, predecessors="A19")), "past the approved deadline")

    def test_over_budget(self):
        self.rejects("TC-50", "Schedule", "New activity exceeds approved budget", lambda: sv.save_activity(self.new_activity(other_cost=900000)), "above the approved budget")

    def test_bad_dependency(self):
        self.rejects("TC-51", "Schedule", "Malformed dependency text", lambda: sv.save_activity(self.new_activity(predecessors="A22XX")), "not a valid dependency")

    def test_unknown_dependency(self):
        self.rejects("TC-52", "Schedule", "Unknown predecessor", lambda: sv.save_activity(self.new_activity(predecessors="A99")), "does not exist")

    def test_zero_duration(self):
        self.rejects("TC-53", "Schedule", "Zero duration", lambda: sv.save_activity(self.new_activity(duration=0)), "at least 1")

    def test_no_assignee(self):
        self.rejects("TC-54", "Schedule", "No team member assigned", lambda: sv.save_activity(self.new_activity(alloc_6=0)), "Assign at least one")

    def test_cycle_through_service(self):
        a = self.activity("A16")
        self.rejects("TC-55", "Schedule", "Edit creates dependency loop", lambda: sv.save_activity({"name": a["name"], "wbs_id": a["wbs_id"], "duration": a["duration"], "other_cost": a["other_cost"], "predecessors": "A19", "alloc_2": 100}, a["id"]), "loop")

    def test_started_locked(self):
        a = self.activity("A06")
        self.rejects("TC-56", "Schedule", "Change duration of started activity", lambda: sv.save_activity({"name": a["name"], "wbs_id": a["wbs_id"], "duration": 20, "other_cost": a["other_cost"], "predecessors": "A04", "alloc_2": 100}, a["id"]), "plan is locked")

    def test_predecessor_not_finished(self):
        a = self.activity("A16")
        self.rejects("TC-57", "Schedule", "Start A16 before predecessors finish", lambda: sv.record_progress(a["id"], {"pct": 10, "log_date": "2026-11-11"}), "cannot start")

    def test_progress_future(self):
        a = self.activity("A10")
        self.rejects("TC-58", "Schedule", "Progress after status date", lambda: sv.record_progress(a["id"], {"pct": 50, "log_date": "2026-12-01"}), "status date")

    def test_case_delays(self):
        s = sv.schedule()
        self.case("TC-59", "Schedule", "Forecast deadline slip in sample data", (80, 85, 5), (s["plan_finish"], s["fc_finish"], s["deadline_slip"]))

    def test_delay_report(self):
        codes = [r["code"] for r in sv.delay_report() if r["state"] == "Delayed"]
        self.case("TC-60", "Schedule", "A16 reported as delayed by inheritance", True, "A16" in codes)

    def test_what_if(self):
        r = sv.run_what_if("A10", 3)
        self.case("TC-61", "Schedule", "What-if: +3 days on critical A10", (3, True), (r["finish_shift"], "A19" in r["shifted"]))

    def test_overallocation(self):
        fe2 = next(p for p in sv.resources()["people"] if p["name"] == "Hamza Raza")
        self.case("TC-62", "Schedule", "Over-allocation detected", True, fe2["over_days"] > 0)

    def test_milestone_state(self):
        states = {m["name"]: m["state"] for m in sv.milestones()}
        self.case("TC-63", "Schedule", "Milestone states", ("Achieved", "At risk"), (states["Charter approved"], states["Go-live"]))


class Cost(Base):
    def test_budget_formula(self):
        a = self.activity("A02")
        self.case("TC-64", "Cost", "A02: 8d x (17000x.5 + 14000x.5 + 11000x.5) + 45000", 213000, scalar("SELECT budget FROM v_activity_budget WHERE activity_id=?", a["id"]))

    def test_bac_sum(self):
        self.case("TC-65", "Cost", "BAC equals sum of activity budgets", 4691000, sv.evm().bac)

    def test_add_cost_changes_ac(self):
        before = sv.evm().ac
        sv.add_cost({"activity_id": self.activity("A10")["id"], "entry_date": "2026-11-11", "amount": 10000, "category": "Software"})
        self.case("TC-66", "Cost", "Recording expenditure raises AC", before + 10000, sv.evm().ac)

    def test_cost_not_started(self):
        self.rejects("TC-67", "Cost", "Cost on unstarted activity", lambda: sv.add_cost({"activity_id": self.activity("A17")["id"], "entry_date": "2026-11-11", "amount": 1, "category": "Other"}), "has not started")

    def test_negative_cost(self):
        self.rejects("TC-68", "Cost", "Negative amount", lambda: sv.add_cost({"activity_id": self.activity("A10")["id"], "entry_date": "2026-11-11", "amount": -1, "category": "Other"}), "at least 1")

    def test_text_cost(self):
        self.rejects("TC-69", "Cost", "Non-numeric amount", lambda: sv.add_cost({"activity_id": self.activity("A10")["id"], "entry_date": "2026-11-11", "amount": "abc", "category": "Other"}), "whole number")

    def test_bad_date(self):
        self.rejects("TC-70", "Cost", "Invalid date", lambda: sv.add_cost({"activity_id": self.activity("A10")["id"], "entry_date": "2026-13-45", "amount": 1, "category": "Other"}), "valid date")

    def test_ev_recomputed(self):
        a = self.activity("A10")
        budget = scalar("SELECT budget FROM v_activity_budget WHERE activity_id=?", a["id"])
        before = sv.evm().ev
        sv.record_progress(a["id"], {"pct": 50, "log_date": "2026-11-11"})
        self.case("TC-71", "EVM", "EV rises by budget x progress gained", round(before + budget * .1), round(sv.evm().ev))

    def test_sample_warnings(self):
        titles = " ".join(w["title"] for w in sv.performance_warnings())
        self.case("TC-72", "EVM", "Sample data triggers cost and schedule warnings", True, "CPI" in titles and "SPI" in titles and "Forecast cost overrun" in titles)

    def test_threshold_setting(self):
        sv.save_settings({**dict(sv.project()), "cpi_warn": .5, "cpi_crit": .4, "spi_warn": .5, "spi_crit": .4})
        titles = " ".join(w["title"] for w in sv.performance_warnings())
        self.case("TC-73", "EVM", "Lower thresholds silence CPI and SPI warnings", False, "CPI" in titles or "SPI" in titles)

    def test_status_date_guard(self):
        self.rejects("TC-74", "EVM", "Status date before recorded actuals", lambda: sv.save_settings({**dict(sv.project()), "status_date": "2026-10-01"}), "recorded actuals")


class Quality(Base):
    def defect(self, code):
        return dict(one("SELECT * FROM defects WHERE code=?", code))

    def test_defect_blocks_completion(self):
        a = self.activity("A21")
        self.rejects("TC-75", "Quality", "Complete activity with critical defects", lambda: sv.record_progress(a["id"], {"pct": 100, "log_date": "2026-11-11"}), "defects are unresolved")

    def test_rework_posts(self):
        before = sv.evm().ac
        d = self.defect("D-001")
        sv.save_defect({**d, "status": "Resolved", "resolved_date": "2026-11-11", "resolution": "Unique constraint added."}, d["id"])
        self.case("TC-76", "Quality", "Resolving posts rework to actual cost", before + 45000, sv.evm().ac)

    def test_rework_once(self):
        d = self.defect("D-001")
        data = {**d, "status": "Resolved", "resolved_date": "2026-11-11", "resolution": "Fixed."}
        sv.save_defect(data, d["id"])
        sv.save_defect(data, d["id"])
        self.case("TC-77", "Quality", "Rework is not posted twice", 1, scalar("SELECT COUNT(*) FROM cost_entries WHERE defect_id=?", d["id"]))

    def test_resolution_needed(self):
        d = self.defect("D-001")
        self.rejects("TC-78", "Quality", "Resolve without a note", lambda: sv.save_defect({**d, "status": "Resolved", "resolved_date": "2026-11-11", "resolution": ""}, d["id"]), "resolution note")

    def test_assignment_needed(self):
        d = self.defect("D-001")
        self.rejects("TC-79", "Quality", "In Progress with no assignee", lambda: sv.save_defect({**d, "status": "In Progress", "assignee_id": ""}, d["id"]), "must be assigned")

    def test_bad_severity(self):
        d = self.defect("D-001")
        self.rejects("TC-80", "Quality", "Invalid severity", lambda: sv.save_defect({**d, "severity": "Huge"}, d["id"]), "Severity must be")

    def test_check_pass_blocked(self):
        item = scalar("SELECT id FROM checklist_items WHERE criterion LIKE 'No double%'")
        self.rejects("TC-81", "Quality", "Pass a check while critical defects are open", lambda: sv.record_inspection(item, {"result": "Pass", "result_date": "2026-11-11", "inspector_id": 7}), "cannot pass")

    def test_inspection_recorded(self):
        item = scalar("SELECT id FROM checklist_items WHERE criterion LIKE 'Lab report%'")
        sv.record_inspection(item, {"result": "Pass", "result_date": "2026-11-11", "inspector_id": 7})
        self.case("TC-82", "Quality", "Inspection result saved", "Pass", next(c["result"] for c in sv.checklist() if c["id"] == item))

    def test_fail_needs_notes(self):
        item = scalar("SELECT id FROM checklist_items WHERE criterion LIKE 'Lab report%'")
        self.rejects("TC-83", "Quality", "Fail with no notes", lambda: sv.record_inspection(item, {"result": "Fail", "result_date": "2026-11-11", "inspector_id": 7}), "Notes is required")

    def test_risk_rank(self):
        top = sv.risk_list()[0]
        self.case("TC-84", "Risk", "Top risk by likelihood x impact", ("RK-01", 20, "High", 1), (top["code"], top["score"], top["rating"], top["rank"]))

    def test_risk_bounds(self):
        wbs = scalar("SELECT id FROM wbs_items WHERE kind='Deliverable'")
        self.rejects("TC-85", "Risk", "Likelihood above 5", lambda: sv.save_risk({"title": "X", "kind": "Risk", "wbs_id": wbs, "likelihood": 6, "impact": 1, "status": "Open"}), "at most 5")

    def test_pdpc(self):
        groups = sv.pdpc()
        responses = sum(len(r["responses"]) for g in groups for r in g["risks"])
        self.case("TC-86", "Risk", "PDPC holds deliverables, problems and countermeasures", (4, 6, 14), (len(groups), sum(len(g["risks"]) for g in groups), responses))


class System(Base):
    PAGES = ["/", "/report", "/charter", "/charter/edit", "/plan", "/plan/edit", "/status", "/status/new", "/closure", "/requirements", "/requirements/new",
             "/wbs", "/wbs/new", "/changes", "/changes/new", "/changes/1", "/changes/2", "/activities", "/activities/new", "/activities/1/edit",
             "/activities/1/progress", "/gantt", "/delays", "/delays?code=A10&days=3", "/resources", "/costs", "/costs/new", "/evm", "/defects", "/defects/new",
             "/defects/1/edit", "/quality", "/quality/new", "/quality/1/result", "/risks", "/risks/new", "/pdpc", "/settings", "/audit"]

    def test_all_pages(self):
        bad = [(p, self.client.get(p).status_code) for p in self.PAGES if self.client.get(p).status_code != 200]
        self.case("TC-87", "System", f"All {len(self.PAGES)} pages load", [], bad)

    def test_pages_after_approval(self):
        self.approve()
        bad = [(p, self.client.get(p).status_code) for p in self.PAGES if self.client.get(p).status_code != 200]
        self.case("TC-88", "System", "All pages load after CR approval", [], bad)

    def test_not_found(self):
        self.case("TC-89", "System", "Missing record returns friendly 404", 404, self.client.get("/defects/999/edit").status_code)

    def test_form_error(self):
        r = self.client.post("/requirements/new", data={"title": "", "priority": "Must"})
        self.case("TC-90", "System", "Invalid form re-displays with message", (200, True), (r.status_code, b"Title is required" in r.data))

    def test_ui_approval(self):
        r = self.client.post("/changes/1/approve", data={"decided_by": "PM"})
        self.case("TC-91", "System", "Approve CR through the web interface", (302, 5800000), (r.status_code, sv.project()["approved_budget"]))

    def test_csrf(self):
        path = TMP / "csrf.db"
        shutil.copy(TEMPLATE, path)
        app = create_app(path, testing=False)
        self.case("TC-92", "System", "POST without security token refused", 400, app.test_client().post("/changes/1/approve", data={"decided_by": "x"}).status_code)

    def test_foreign_keys(self):
        self.rejects("TC-93", "System", "Foreign key integrity enforced", lambda: db().execute("INSERT INTO cost_entries(activity_id, entry_date, amount, category) VALUES (9999,'2026-11-01',1,'Other')"), "FOREIGN KEY")

    def test_xss(self):
        rid = sv.save_requirement({"title": "<script>alert(1)</script>", "priority": "Could"})
        body = self.client.get("/requirements").data
        self.case("TC-94", "System", "User text is HTML-escaped", (False, True), (b"<script>alert(1)" in body, rid > 0))

    def test_sql_injection(self):
        sv.save_requirement({"title": "x'); DROP TABLE requirements;--", "priority": "Could"})
        self.case("TC-95", "System", "SQL injection text is stored harmlessly", 11, scalar("SELECT COUNT(*) FROM requirements"))

    def test_trace(self):
        r = next(x for x in sv.traceability() if x["code"] == "R-001")
        self.case("TC-96", "System", "Traceability links requirement to work and defects", True, r["activities"] > 0 and r["budget"] > 0 and r["open_defects"] == 3)

    def test_page_content(self):
        expect = {"/pdpc": b"Add a database unique constraint", "/risks": b"RK-01", "/wbs": b"1.3.1", "/gantt": b"Go-live", "/evm": b"Earned Value (EV)",
                  "/status": b"Accountable", "/costs": b"BCWP", "/quality": b"No double-booking", "/charter": b"Dr. Imran Qureshi", "/changes/1": b"After approval",
                  "/resources": b"Hamza Raza", "/delays": b"Inherited from", "/report": b"Requirement traceability", "/": b"Unresolved critical defects"}
        missing = [p for p, text in expect.items() if text not in self.client.get(p).data]
        self.case("TC-98", "System", "Each page displays its module data", [], missing)

    def test_dashboard(self):
        d = sv.dashboard()
        self.case("TC-97", "System", "Dashboard totals", (1, 2, True), (len(d["pending"]), len(d["critical"]), len(d["delayed"]) > 0))


def write_report():
    out = ROOT / "submission"
    out.mkdir(exist_ok=True)
    data = sorted(RESULTS, key=lambda r: r[0])
    with open(out / "Test_Cases.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Test ID", "Module", "Test case", "Expected result", "Actual result", "Status"])
        for r in data:
            w.writerow([*r[:5], "Pass" if r[5] else "Fail"])
    passed = sum(1 for r in data if r[5])
    body = "".join(
        f"<tr><td>{r[0]}</td><td>{r[1]}</td><td>{html.escape(r[2])}</td><td>{html.escape(r[3])}</td><td>{html.escape(r[4])}</td>"
        f"<td class={'p' if r[5] else 'f'}>{'Pass' if r[5] else 'Fail'}</td></tr>" for r in data)
    (out / "Test_Report.html").write_text(
        "<!doctype html><meta charset=utf-8><title>Test Report</title><style>body{font:13px 'Segoe UI',sans-serif;margin:28px;color:#1b2430}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #e1e5ea;padding:5px 8px;text-align:left;vertical-align:top}th{background:#f5f6f8}"
        ".p{color:#0b7a55;font-weight:600}.f{color:#b3261e;font-weight:600}</style>"
        f"<h1>Test Cases: Expected and Actual Results</h1><p><b>{passed} of {len(data)} passed.</b></p>"
        f"<table><tr><th>ID</th><th>Module</th><th>Test case</th><th>Expected</th><th>Actual</th><th>Status</th></tr>{body}</table>", encoding="utf-8")
    print(f"\n{passed} of {len(data)} cases passed. Report: {out / 'Test_Report.html'}")


if __name__ == "__main__":
    program = unittest.main(exit=False, verbosity=1)
    write_report()
    sys.exit(0 if program.result.wasSuccessful() else 1)
