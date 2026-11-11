"""Web routes. Views only collect input and render; rules live in services.py."""
from __future__ import annotations

import sqlite3

from flask import abort, flash, redirect, render_template, request, url_for

from . import services as sv
from .db import ValidationError, close_db, one, rows, scalar
from .engine import ScheduleError

ERRORS = (ValidationError, ScheduleError, sqlite3.IntegrityError)


def F(name, label, type="text", options=None, required=True, help=None, **extra):
    return {"name": name, "label": label, "type": type, "options": options, "required": required, "help": help, **extra}


def form_page(title, fields, values, handler, back, success="Saved.", intro=None):
    """Render a form, run the handler on POST, and keep input when validation fails."""
    if request.method == "POST":
        try:
            handler(request.form)
        except ERRORS as exc:
            flash(str(exc), "error")
            values = request.form
        else:
            flash(success, "ok")
            return redirect(back)
    return render_template("form.html", title=title, fields=fields, values=values, back=back, intro=intro)


def act(handler, back, success="Saved."):
    """Run a button action and return to the page."""
    try:
        handler()
    except ERRORS as exc:
        flash(str(exc), "error")
    else:
        flash(success, "ok")
    return redirect(back)


def record(table, item_id):
    row = one(f"SELECT * FROM {table} WHERE id=?", item_id)
    if not row:
        abort(404)
    return dict(row)


def member_options():
    return [(m["id"], f"{m['name']} ({m['role']})") for m in rows("SELECT * FROM team_members ORDER BY id")]


def activity_options():
    return [(a["id"], f"{a['code']} {a['name']}") for a in rows("SELECT * FROM activities ORDER BY id")]


def wbs_options(kind=None):
    return [(w["id"], f"{w['code']} {w['title']}") for w in sv.wbs_tree() if kind is None or w["kind"] in kind]


def approved_requirement_options():
    return [(r["id"], f"{r['code']} {r['title']}") for r in rows("SELECT * FROM requirements WHERE status='Approved' ORDER BY code")]


def plain(values):
    return [(v, v) for v in values]


def register(app):
    route = app.route
    GP = ["GET", "POST"]

    # ------------------------------------------------------------ overview
    @route("/")
    def dashboard_page():
        return render_template("dashboard.html", **sv.dashboard())

    @route("/report")
    def report_page():
        data = sv.dashboard()
        return render_template("report.html", **data, acts=sv.activity_rows(data["s"]),
                               trace=sv.traceability(),
                               changes=rows("SELECT * FROM change_requests ORDER BY code"))

    # ------------------------------------------------------------ 1 integration
    @route("/charter")
    def charter_page():
        return render_template("charter.html", p=sv.project(), objectives=rows("SELECT * FROM objectives"),
                               stakeholders=rows("SELECT * FROM stakeholders"))

    @route("/charter/edit", methods=GP)
    def charter_edit():
        fields = [F("name", "Project name"), F("client", "Client"), F("description", "Description", "textarea", required=False),
                  F("start_date", "Start date", "date"), F("deadline", "Deadline", "date"),
                  F("approved_budget", "Approved budget (PKR)", "number"),
                  F("scope_in", "In scope (one per line)", "textarea"), F("scope_out", "Out of scope (one per line)", "textarea")]
        return form_page("Edit project charter", fields, dict(sv.project()), sv.save_charter, url_for("charter_page"))

    def objective_fields():
        return [F("text", "Objective"), F("measure", "Success measure", required=False)]

    @route("/objectives/new", methods=GP)
    def objective_new():
        return form_page("Add objective", objective_fields(), {}, sv.save_objective, url_for("charter_page"))

    @route("/objectives/<int:i>/edit", methods=GP)
    def objective_edit(i):
        return form_page("Edit objective", objective_fields(), record("objectives", i), lambda f: sv.save_objective(f, i), url_for("charter_page"))

    def stakeholder_fields():
        return [F("name", "Name"), F("role", "Role"), F("organization", "Organization", required=False),
                F("influence", "Influence", "select", plain(["High", "Medium", "Low"]))]

    @route("/stakeholders/new", methods=GP)
    def stakeholder_new():
        return form_page("Add stakeholder", stakeholder_fields(), {}, sv.save_stakeholder, url_for("charter_page"))

    @route("/stakeholders/<int:i>/edit", methods=GP)
    def stakeholder_edit(i):
        return form_page("Edit stakeholder", stakeholder_fields(), record("stakeholders", i), lambda f: sv.save_stakeholder(f, i), url_for("charter_page"))

    @route("/plan")
    def plan_page():
        s = sv.schedule()
        return render_template("plan.html", p=s["project"], s=s, snap=sv.snapshot(), baselines=rows("SELECT * FROM baselines ORDER BY version"),
                               scope=rows("SELECT * FROM requirements WHERE status='Approved' ORDER BY code"),
                               checks=len(sv.checklist()))

    @route("/plan/edit", methods=GP)
    def plan_edit():
        fields = [F("plan_scope", "Scope management", "textarea"), F("plan_schedule", "Schedule management", "textarea"),
                  F("plan_cost", "Cost management", "textarea"), F("plan_quality", "Quality management", "textarea")]
        return form_page("Edit project management plan", fields, dict(sv.project()), sv.save_plan, url_for("plan_page"))

    @route("/status")
    def status_page():
        team = rows("SELECT * FROM team_members ORDER BY id")
        matrix = {}
        for r in rows("SELECT * FROM responsibilities"):
            matrix.setdefault(r["area"], {})[r["member_id"]] = r["raci"]
        return render_template("status.html", p=sv.project(), log=rows("SELECT * FROM status_log ORDER BY log_date DESC, id DESC"),
                               milestones=sv.milestones(), team=team, matrix=matrix)

    @route("/status/new", methods=GP)
    def status_new():
        fields = [F("status", "Project status", "select", plain(sv.PROJECT_STATUSES)), F("summary", "Status summary", "textarea")]
        return form_page("Update project status", fields, {"status": sv.project()["status"]}, sv.add_status, url_for("status_page"))

    def milestone_fields():
        return [F("name", "Milestone"), F("activity_id", "Reached when this activity finishes", "select", activity_options())]

    @route("/milestones/new", methods=GP)
    def milestone_new():
        return form_page("Add milestone", milestone_fields(), {}, sv.save_milestone, url_for("status_page"))

    @route("/milestones/<int:i>/edit", methods=GP)
    def milestone_edit(i):
        return form_page("Edit milestone", milestone_fields(), record("milestones", i), lambda f: sv.save_milestone(f, i), url_for("status_page"))

    @route("/responsibilities/new", methods=GP)
    def responsibility_new():
        fields = [F("area", "Responsibility area"), F("member_id", "Team member", "select", member_options()),
                  F("raci", "RACI role", "select", [("R", "Responsible"), ("A", "Accountable"), ("C", "Consulted"), ("I", "Informed")])]
        return form_page("Assign responsibility", fields, {}, sv.save_responsibility, url_for("status_page"))

    @route("/closure", methods=GP)
    def closure_page():
        if request.method == "POST":
            return act(lambda: sv.close_project(request.form), url_for("closure_page"), "Project closed.")
        return render_template("closure.html", p=sv.project(), checks=sv.closure_checks(), record=one("SELECT * FROM closure"))

    # ------------------------------------------------------------ 2 scope
    @route("/requirements")
    def requirements_page():
        return render_template("requirements.html", items=sv.traceability())

    def requirement_fields():
        return [F("title", "Title"), F("description", "Description", "textarea", required=False),
                F("priority", "Priority (MoSCoW)", "select", plain(sv.PRIORITIES)), F("source", "Source", required=False)]

    @route("/requirements/new", methods=GP)
    def requirement_new():
        return form_page("Add requirement", requirement_fields(), {"priority": "Should"}, sv.save_requirement, url_for("requirements_page"))

    @route("/requirements/<int:i>/edit", methods=GP)
    def requirement_edit(i):
        return form_page("Edit requirement", requirement_fields(), record("requirements", i), lambda f: sv.save_requirement(f, i), url_for("requirements_page"))

    @route("/requirements/<int:i>/<any(approve,reject):decision>", methods=["POST"])
    def requirement_decide(i, decision):
        status = "Approved" if decision == "approve" else "Rejected"
        return act(lambda: sv.decide_requirement(i, status), url_for("requirements_page"), f"Requirement {status.lower()}.")

    @route("/wbs")
    def wbs_page():
        return render_template("wbs.html", tree=sv.wbs_tree())

    @route("/wbs/generate", methods=["POST"])
    def wbs_generate():
        def run():
            count = sv.generate_wbs()
            flash(f"{count} approved requirement(s) added to the WBS." if count else "All approved requirements are already in the WBS.", "ok")
        try:
            run()
        except ERRORS as exc:
            flash(str(exc), "error")
        return redirect(url_for("wbs_page"))

    def wbs_fields():
        return [F("title", "Title"), F("kind", "Type", "select", plain(["Deliverable", "Work Package"])),
                F("parent_id", "Parent", "select", wbs_options(("Project", "Deliverable"))),
                F("requirement_id", "Approved requirement", "select", approved_requirement_options(), required=False,
                  help="Only approved requirements can be selected.")]

    @route("/wbs/new", methods=GP)
    def wbs_new():
        return form_page("Add WBS item", wbs_fields(), {"kind": "Work Package"}, sv.save_wbs, url_for("wbs_page"))

    @route("/wbs/<int:i>/edit", methods=GP)
    def wbs_edit(i):
        item = record("wbs_items", i)
        if item["kind"] == "Project":
            abort(404)
        return form_page("Edit WBS item", wbs_fields(), item, lambda f: sv.save_wbs(f, i), url_for("wbs_page"))

    @route("/wbs/<int:i>/delete", methods=["POST"])
    def wbs_delete(i):
        return act(lambda: sv.delete_wbs(i), url_for("wbs_page"), "WBS item deleted.")

    @route("/changes")
    def changes_page():
        return render_template("changes.html", items=rows("SELECT * FROM change_requests ORDER BY code DESC"),
                               baselines=rows("SELECT b.*, c.code cr_code FROM baselines b LEFT JOIN change_requests c ON c.id=b.cr_id ORDER BY version"))

    def change_fields():
        return [F("title", "Title"), F("description", "Proposed change", "textarea", required=False), F("justification", "Justification", "textarea"),
                F("requested_by", "Requested by"), F("cost_impact", "Cost impact (PKR)", "number"),
                F("schedule_impact_days", "Schedule impact (working days)", "number", help="5 working days = 1 week.")]

    @route("/changes/new", methods=GP)
    def change_new():
        if request.method == "POST":
            try:
                new_id = sv.save_change(request.form)
            except ERRORS as exc:
                flash(str(exc), "error")
                return render_template("form.html", title="Raise change request", fields=change_fields(), values=request.form, back=url_for("changes_page"), intro=None)
            flash("Change request raised. Now link requirements and add work items.", "ok")
            return redirect(url_for("change_detail", i=new_id))
        return render_template("form.html", title="Raise change request", fields=change_fields(), values={}, back=url_for("changes_page"), intro=None)

    @route("/changes/<int:i>")
    def change_detail(i):
        cr = record("change_requests", i)
        return render_template("change_detail.html", cr=cr, items=sv.work_items(i), preview=sv.preview_change(i) if cr["status"] == "Pending" else None,
                               reqs=rows("SELECT * FROM requirements WHERE cr_id=? ORDER BY code", i),
                               free=rows("SELECT * FROM requirements WHERE status='Proposed' AND cr_id IS NULL ORDER BY code"),
                               baselines=rows("SELECT * FROM baselines WHERE cr_id=? OR version=(SELECT version-1 FROM baselines WHERE cr_id=?) ORDER BY version", i, i))

    @route("/changes/<int:i>/edit", methods=GP)
    def change_edit(i):
        return form_page("Edit change request", change_fields(), record("change_requests", i), lambda f: sv.save_change(f, i), url_for("change_detail", i=i))

    @route("/changes/<int:i>/link", methods=["POST"])
    def change_link(i):
        return act(lambda: sv.link_requirement(i, request.form), url_for("change_detail", i=i), "Requirement linked.")

    @route("/changes/<int:i>/unlink/<int:r>", methods=["POST"])
    def change_unlink(i, r):
        return act(lambda: sv.unlink_requirement(i, r), url_for("change_detail", i=i), "Requirement removed.")

    def item_fields(i):
        reqs = [(r["id"], f"{r['code']} {r['title']}") for r in rows("SELECT * FROM requirements WHERE cr_id=?", i)]
        return [F("requirement_id", "Requirement", "select", reqs), F("name", "Work item name"), F("duration", "Duration (working days)", "number"),
                F("member_id", "Team member", "select", member_options()), F("allocation", "Allocation %", "number"),
                F("other_cost", "Other cost (PKR)", "number", required=False),
                F("predecessors", "Predecessors", required=False, help="Activity codes or work item refs, for example A16, W1 or A02SS+2."),
                F("successors", "Successors", required=False, help="Existing activities that must wait for this work, for example A17.")]

    @route("/changes/<int:i>/items/new", methods=GP)
    def item_new(i):
        return form_page("Add work item", item_fields(i), {"allocation": 100, "other_cost": 0}, lambda f: sv.save_work_item(i, f), url_for("change_detail", i=i))

    @route("/changes/<int:i>/items/<int:w>/edit", methods=GP)
    def item_edit(i, w):
        return form_page("Edit work item", item_fields(i), record("cr_work_items", w), lambda f: sv.save_work_item(i, f, w), url_for("change_detail", i=i))

    @route("/changes/<int:i>/items/<int:w>/delete", methods=["POST"])
    def item_delete(i, w):
        return act(lambda: sv.delete_work_item(i, w), url_for("change_detail", i=i), "Work item deleted.")

    @route("/changes/<int:i>/<any(approve,reject):decision>", methods=["POST"])
    def change_decide(i, decision):
        status = "Approved" if decision == "approve" else "Rejected"
        return act(lambda: sv.decide_change(i, request.form, status), url_for("change_detail", i=i), f"Change request {status.lower()}.")

    # ------------------------------------------------------------ 3 schedule
    @route("/activities")
    def activities_page():
        s = sv.schedule()
        return render_template("activities.html", s=s, items=sv.activity_rows(s))

    def activity_fields():
        return [F("name", "Activity name"), F("wbs_id", "Work package", "select", wbs_options(("Work Package",))),
                F("duration", "Duration (working days)", "number"), F("other_cost", "Other cost (PKR)", "number", required=False),
                F("predecessors", "Predecessors", required=False, help="For example A01, A02SS+2. Types: FS, SS, FF, SF. Default is FS."),
                F("alloc", "Team allocation %", "alloc", rows("SELECT * FROM team_members ORDER BY id"), required=False,
                  help="Cost is calculated from duration, daily rate and allocation.")]

    @route("/activities/new", methods=GP)
    def activity_new():
        return form_page("Add activity", activity_fields(), {"other_cost": 0}, sv.save_activity, url_for("activities_page"))

    @route("/activities/<int:i>/edit", methods=GP)
    def activity_edit(i):
        values = record("activities", i)
        for a in rows("SELECT * FROM assignments WHERE activity_id=?", i):
            values[f"alloc_{a['member_id']}"] = a["allocation"]
        values["predecessors"] = next(r["preds"] for r in sv.activity_rows() if r["id"] == i)
        return form_page("Edit activity", activity_fields(), values, lambda f: sv.save_activity(f, i), url_for("activities_page"))

    @route("/activities/<int:i>/delete", methods=["POST"])
    def activity_delete(i):
        return act(lambda: sv.delete_activity(i), url_for("activities_page"), "Activity deleted.")

    @route("/activities/<int:i>/progress", methods=GP)
    def activity_progress(i):
        a = record("activities", i)
        fields = [F("pct", "Percent complete", "number"), F("log_date", "Progress date", "date"), F("actual_start", "Actual start", "date", required=False),
                  F("remaining_days", "Remaining days (optional)", "number", required=False, help="Leave blank to calculate from percent complete.")]
        values = {**a, "log_date": sv.project()["status_date"]}
        return form_page(f"Update progress: {a['code']} {a['name']}", fields, values, lambda f: sv.record_progress(i, f), url_for("activities_page"), "Progress recorded.")

    @route("/gantt")
    def gantt_page():
        s = sv.schedule()
        items = sorted(sv.activity_rows(s), key=lambda r: (r["es"], r["code"]))
        span = max(s["plan_finish"], s["fc_finish"], s["deadline_offset"]) + 3
        weeks = [(w, s["cal"].date_of(w)) for w in range(0, span, 5)]
        px = max(6, min(11, 810 / span))
        return render_template("gantt.html", s=s, items=items, span=span, px=px, weeks=weeks, milestones=sv.milestones(s))

    @route("/delays")
    def delays_page():
        s = sv.schedule()
        result = None
        code = request.args.get("code")
        if code:
            try:
                result = sv.run_what_if(code, request.args.get("days"))
            except ERRORS as exc:
                flash(str(exc), "error")
        open_items = [a for a in sv.activity_rows(s) if not a["actual_finish"]]
        return render_template("delays.html", s=s, items=sv.delay_report(s), result=result, open_items=open_items)

    @route("/resources")
    def resources_page():
        return render_template("resources.html", team=rows("SELECT * FROM team_members ORDER BY id"), **sv.resources())

    def member_fields():
        return [F("name", "Name"), F("role", "Role"), F("daily_rate", "Daily rate (PKR)", "number")]

    @route("/team/new", methods=GP)
    def member_new():
        return form_page("Add team member", member_fields(), {}, sv.save_member, url_for("resources_page"))

    @route("/team/<int:i>/edit", methods=GP)
    def member_edit(i):
        return form_page("Edit team member", member_fields(), record("team_members", i), lambda f: sv.save_member(f, i), url_for("resources_page"))

    # ------------------------------------------------------------ 4 cost
    @route("/costs")
    def costs_page():
        s = sv.schedule()
        return render_template("costs.html", p=s["project"], items=sv.activity_rows(s), evm=sv.evm(s),
                               entries=rows("""SELECT e.*, a.code FROM cost_entries e JOIN activities a ON a.id=e.activity_id
                                               ORDER BY e.entry_date DESC, e.id DESC LIMIT 40"""))

    @route("/costs/new", methods=GP)
    def cost_new():
        fields = [F("activity_id", "Activity", "select", activity_options()), F("entry_date", "Date", "date"), F("amount", "Amount (PKR)", "number"),
                  F("category", "Category", "select", plain(sv.COST_CATEGORIES)), F("description", "Description", required=False)]
        return form_page("Record expenditure", fields, {"entry_date": sv.project()["status_date"]}, sv.add_cost, url_for("costs_page"), "Expenditure recorded.")

    @route("/costs/<int:i>/delete", methods=["POST"])
    def cost_delete(i):
        return act(lambda: sv.delete_cost(i), url_for("costs_page"), "Entry deleted.")

    @route("/evm")
    def evm_page():
        s = sv.schedule()
        return render_template("evm.html", p=s["project"], evm=sv.evm(s), warnings=sv.performance_warnings(s), curve=sv.s_curve(s))

    # ------------------------------------------------------------ 5 quality and risk
    @route("/defects")
    def defects_page():
        items = rows("""SELECT f.*, a.code act, m.name assignee FROM defects f JOIN activities a ON a.id=f.activity_id
                        LEFT JOIN team_members m ON m.id=f.assignee_id
                        ORDER BY f.status IN ('Resolved','Closed'), CASE f.severity WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END, f.code""")
        return render_template("defects.html", items=items)

    def defect_fields():
        return [F("title", "Title"), F("description", "Description", "textarea", required=False), F("severity", "Severity", "select", plain(sv.SEVERITIES)),
                F("status", "Status", "select", plain(sv.DEFECT_STATUSES)), F("assignee_id", "Assigned to", "select", member_options(), required=False),
                F("activity_id", "Related activity", "select", activity_options()), F("found_date", "Found date", "date"),
                F("resolved_date", "Resolved date", "date", required=False), F("resolution", "Resolution", "textarea", required=False),
                F("rework_cost", "Rework cost (PKR)", "number", required=False, help="Posted to actual cost when the defect is resolved.")]

    @route("/defects/new", methods=GP)
    def defect_new():
        return form_page("Record defect", defect_fields(), {"status": "Open", "found_date": sv.project()["status_date"], "rework_cost": 0}, sv.save_defect, url_for("defects_page"))

    @route("/defects/<int:i>/edit", methods=GP)
    def defect_edit(i):
        return form_page("Update defect", defect_fields(), record("defects", i), lambda f: sv.save_defect(f, i), url_for("defects_page"))

    @route("/quality")
    def quality_page():
        return render_template("quality.html", items=sv.checklist())

    @route("/quality/new", methods=GP)
    def check_new():
        fields = [F("wbs_id", "Deliverable", "select", wbs_options(("Deliverable",))), F("criterion", "Acceptance criterion"), F("method", "Method", "select", plain(["Inspection", "Test"]))]
        return form_page("Add quality check", fields, {}, sv.save_check, url_for("quality_page"))

    @route("/quality/<int:i>/result", methods=GP)
    def check_result(i):
        item = record("checklist_items", i)
        fields = [F("result", "Result", "select", plain(["Pass", "Fail"])), F("result_date", "Date", "date"), F("inspector_id", "Inspector", "select", member_options()), F("notes", "Notes", "textarea", required=False, help="Required for a failed check.")]
        return form_page("Record result", fields, {"result_date": sv.project()["status_date"]}, lambda f: sv.record_inspection(i, f), url_for("quality_page"), "Result recorded.", intro=item["criterion"])

    @route("/risks")
    def risks_page():
        items = sv.risk_list()
        cells = {}
        for r in items:
            if r["status"] != "Closed":
                cells.setdefault((r["likelihood"], r["impact"]), []).append(r)
        return render_template("risks.html", items=items, cells=cells, rating=sv.rating)

    def risk_fields():
        scale = [(i, str(i)) for i in range(1, 6)]
        return [F("title", "Title"), F("kind", "Type", "select", plain(["Risk", "Issue"])), F("wbs_id", "Deliverable", "select", wbs_options(("Deliverable",))),
                F("likelihood", "Likelihood (1-5)", "select", scale), F("impact", "Impact (1-5)", "select", scale),
                F("owner_id", "Owner", "select", member_options(), required=False), F("status", "Status", "select", plain(["Open", "Mitigating", "Closed"]))]

    @route("/risks/new", methods=GP)
    def risk_new():
        return form_page("Add risk or issue", risk_fields(), {"status": "Open"}, sv.save_risk, url_for("risks_page"))

    @route("/risks/<int:i>/edit", methods=GP)
    def risk_edit(i):
        return form_page("Edit risk or issue", risk_fields(), record("risks", i), lambda f: sv.save_risk(f, i), url_for("risks_page"))

    @route("/pdpc")
    def pdpc_page():
        return render_template("pdpc.html", p=sv.project(), groups=sv.pdpc())

    @route("/risks/<int:i>/responses/new", methods=GP)
    def response_new(i):
        risk = record("risks", i)
        fields = [F("type", "Type", "select", plain(["Preventive", "Corrective"])), F("action", "Action"), F("feasible", "Feasible?", "select", [("1", "Yes"), ("0", "No")])]
        return form_page("Add countermeasure", fields, {}, lambda f: sv.save_response(i, f), url_for("pdpc_page"), intro=risk["title"])

    # ------------------------------------------------------------ system
    @route("/settings", methods=GP)
    def settings_page():
        fields = [F("status_date", "Status date", "date", help="All schedule and earned value figures are calculated as of this date."),
                  F("cpi_warn", "CPI warning below", "number", step="0.01"), F("cpi_crit", "CPI critical below", "number", step="0.01"),
                  F("spi_warn", "SPI warning below", "number", step="0.01"), F("spi_crit", "SPI critical below", "number", step="0.01"),
                  F("budget_warn_pct", "Budget spent warning at (%)", "number"), F("slip_warn_days", "Allowed deadline slip (working days)", "number")]
        return form_page("Settings", fields, dict(sv.project()), sv.save_settings, url_for("settings_page"), "Settings saved.")

    @route("/reset", methods=["POST"], endpoint="reset")
    def reset():
        from . import reset_database
        close_db()
        reset_database(app.config["DB_PATH"])
        flash("Sample data restored.", "ok")
        return redirect(url_for("dashboard_page"))

    @route("/audit")
    def audit_page():
        return render_template("audit.html", items=rows("SELECT * FROM audit_log ORDER BY id DESC LIMIT 200"), count=scalar("SELECT COUNT(*) FROM audit_log"))
