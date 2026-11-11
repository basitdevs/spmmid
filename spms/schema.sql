-- Smart Healthcare Software Project Management System: database schema (SQLite)
-- Dates are ISO text (YYYY-MM-DD). Money is whole PKR. Durations are working days (Mon-Fri).

CREATE TABLE project (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  name TEXT NOT NULL,
  client TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  start_date TEXT NOT NULL,
  deadline TEXT NOT NULL,
  approved_budget INTEGER NOT NULL CHECK (approved_budget > 0),
  scope_in TEXT NOT NULL DEFAULT '',
  scope_out TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'Planning'
    CHECK (status IN ('Initiation','Planning','Execution','On Hold','Closed')),
  status_date TEXT NOT NULL,
  plan_scope TEXT NOT NULL DEFAULT '',
  plan_schedule TEXT NOT NULL DEFAULT '',
  plan_cost TEXT NOT NULL DEFAULT '',
  plan_quality TEXT NOT NULL DEFAULT '',
  plan_version INTEGER NOT NULL DEFAULT 1,
  cpi_warn REAL NOT NULL DEFAULT 0.95,
  cpi_crit REAL NOT NULL DEFAULT 0.85,
  spi_warn REAL NOT NULL DEFAULT 0.95,
  spi_crit REAL NOT NULL DEFAULT 0.85,
  budget_warn_pct REAL NOT NULL DEFAULT 90,
  slip_warn_days INTEGER NOT NULL DEFAULT 3,
  CHECK (deadline >= start_date)
);

CREATE TABLE objectives (
  id INTEGER PRIMARY KEY,
  text TEXT NOT NULL,
  measure TEXT NOT NULL DEFAULT ''
);

CREATE TABLE stakeholders (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  role TEXT NOT NULL,
  organization TEXT NOT NULL DEFAULT '',
  influence TEXT NOT NULL DEFAULT 'Medium' CHECK (influence IN ('Low','Medium','High'))
);

CREATE TABLE team_members (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  role TEXT NOT NULL,
  daily_rate INTEGER NOT NULL CHECK (daily_rate > 0)
);

CREATE TABLE status_log (
  id INTEGER PRIMARY KEY,
  log_date TEXT NOT NULL,
  status TEXT NOT NULL,
  summary TEXT NOT NULL
);

CREATE TABLE responsibilities (
  id INTEGER PRIMARY KEY,
  area TEXT NOT NULL,
  member_id INTEGER NOT NULL REFERENCES team_members(id),
  raci TEXT NOT NULL CHECK (raci IN ('R','A','C','I')),
  UNIQUE (area, member_id)
);

CREATE TABLE change_requests (
  id INTEGER PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  justification TEXT NOT NULL,
  requested_by TEXT NOT NULL,
  raised_on TEXT NOT NULL,
  cost_impact INTEGER NOT NULL CHECK (cost_impact >= 0),
  schedule_impact_days INTEGER NOT NULL CHECK (schedule_impact_days >= 0),
  status TEXT NOT NULL DEFAULT 'Pending' CHECK (status IN ('Pending','Approved','Rejected')),
  decided_on TEXT,
  decided_by TEXT,
  decision_note TEXT
);

CREATE TABLE requirements (
  id INTEGER PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  priority TEXT NOT NULL DEFAULT 'Should' CHECK (priority IN ('Must','Should','Could','Wont')),
  status TEXT NOT NULL DEFAULT 'Proposed' CHECK (status IN ('Proposed','Approved','Rejected')),
  source TEXT NOT NULL DEFAULT '',
  cr_id INTEGER REFERENCES change_requests(id)
);

CREATE TABLE wbs_items (
  id INTEGER PRIMARY KEY,
  parent_id INTEGER REFERENCES wbs_items(id),
  title TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('Project','Deliverable','Work Package')),
  requirement_id INTEGER REFERENCES requirements(id),
  sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE activities (
  id INTEGER PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  wbs_id INTEGER NOT NULL REFERENCES wbs_items(id),
  name TEXT NOT NULL,
  duration INTEGER NOT NULL CHECK (duration >= 1),
  other_cost INTEGER NOT NULL DEFAULT 0 CHECK (other_cost >= 0),
  pct INTEGER NOT NULL DEFAULT 0 CHECK (pct BETWEEN 0 AND 100),
  actual_start TEXT,
  actual_finish TEXT,
  remaining_days INTEGER CHECK (remaining_days IS NULL OR remaining_days >= 1),
  origin_cr_id INTEGER REFERENCES change_requests(id),
  CHECK (actual_finish IS NULL OR actual_start IS NOT NULL),
  CHECK (actual_finish IS NULL OR actual_finish >= actual_start)
);

CREATE TABLE dependencies (
  id INTEGER PRIMARY KEY,
  pred_id INTEGER NOT NULL REFERENCES activities(id),
  succ_id INTEGER NOT NULL REFERENCES activities(id),
  type TEXT NOT NULL DEFAULT 'FS' CHECK (type IN ('FS','SS','FF','SF')),
  lag INTEGER NOT NULL DEFAULT 0,
  UNIQUE (pred_id, succ_id),
  CHECK (pred_id <> succ_id)
);

CREATE TABLE assignments (
  activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
  member_id INTEGER NOT NULL REFERENCES team_members(id),
  allocation INTEGER NOT NULL CHECK (allocation BETWEEN 1 AND 100),
  PRIMARY KEY (activity_id, member_id)
);

CREATE TABLE milestones (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  activity_id INTEGER NOT NULL REFERENCES activities(id)
);

CREATE TABLE progress_log (
  id INTEGER PRIMARY KEY,
  activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
  log_date TEXT NOT NULL,
  pct INTEGER NOT NULL CHECK (pct BETWEEN 0 AND 100)
);

CREATE TABLE defects (
  id INTEGER PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  severity TEXT NOT NULL CHECK (severity IN ('Critical','High','Medium','Low')),
  status TEXT NOT NULL DEFAULT 'Open' CHECK (status IN ('Open','In Progress','Resolved','Closed')),
  assignee_id INTEGER REFERENCES team_members(id),
  activity_id INTEGER NOT NULL REFERENCES activities(id),
  found_date TEXT NOT NULL,
  resolved_date TEXT,
  resolution TEXT NOT NULL DEFAULT '',
  rework_cost INTEGER NOT NULL DEFAULT 0 CHECK (rework_cost >= 0)
);

CREATE TABLE cost_entries (
  id INTEGER PRIMARY KEY,
  activity_id INTEGER NOT NULL REFERENCES activities(id),
  entry_date TEXT NOT NULL,
  amount INTEGER NOT NULL CHECK (amount > 0),
  category TEXT NOT NULL CHECK (category IN ('Labour','Software','Hardware','Services','Rework','Other')),
  description TEXT NOT NULL DEFAULT '',
  defect_id INTEGER REFERENCES defects(id)
);

CREATE TABLE cr_work_items (
  id INTEGER PRIMARY KEY,
  cr_id INTEGER NOT NULL REFERENCES change_requests(id) ON DELETE CASCADE,
  ref TEXT NOT NULL,
  requirement_id INTEGER NOT NULL REFERENCES requirements(id),
  name TEXT NOT NULL,
  duration INTEGER NOT NULL CHECK (duration >= 1),
  member_id INTEGER NOT NULL REFERENCES team_members(id),
  allocation INTEGER NOT NULL DEFAULT 100 CHECK (allocation BETWEEN 1 AND 100),
  other_cost INTEGER NOT NULL DEFAULT 0 CHECK (other_cost >= 0),
  predecessors TEXT NOT NULL DEFAULT '',
  successors TEXT NOT NULL DEFAULT '',
  UNIQUE (cr_id, ref)
);

CREATE TABLE baselines (
  id INTEGER PRIMARY KEY,
  version INTEGER NOT NULL UNIQUE,
  created_on TEXT NOT NULL,
  reason TEXT NOT NULL,
  cr_id INTEGER REFERENCES change_requests(id),
  budget INTEGER NOT NULL,
  bac INTEGER NOT NULL,
  deadline TEXT NOT NULL,
  planned_finish TEXT NOT NULL,
  requirement_count INTEGER NOT NULL,
  wbs_count INTEGER NOT NULL,
  activity_count INTEGER NOT NULL
);

CREATE TABLE checklist_items (
  id INTEGER PRIMARY KEY,
  wbs_id INTEGER NOT NULL REFERENCES wbs_items(id),
  criterion TEXT NOT NULL,
  method TEXT NOT NULL CHECK (method IN ('Inspection','Test'))
);

CREATE TABLE inspection_results (
  id INTEGER PRIMARY KEY,
  item_id INTEGER NOT NULL REFERENCES checklist_items(id) ON DELETE CASCADE,
  result_date TEXT NOT NULL,
  result TEXT NOT NULL CHECK (result IN ('Pass','Fail')),
  inspector_id INTEGER NOT NULL REFERENCES team_members(id),
  notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE risks (
  id INTEGER PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'Risk' CHECK (kind IN ('Risk','Issue')),
  wbs_id INTEGER NOT NULL REFERENCES wbs_items(id),
  likelihood INTEGER NOT NULL CHECK (likelihood BETWEEN 1 AND 5),
  impact INTEGER NOT NULL CHECK (impact BETWEEN 1 AND 5),
  owner_id INTEGER REFERENCES team_members(id),
  status TEXT NOT NULL DEFAULT 'Open' CHECK (status IN ('Open','Mitigating','Closed'))
);

CREATE TABLE risk_responses (
  id INTEGER PRIMARY KEY,
  risk_id INTEGER NOT NULL REFERENCES risks(id) ON DELETE CASCADE,
  type TEXT NOT NULL CHECK (type IN ('Preventive','Corrective')),
  action TEXT NOT NULL,
  feasible INTEGER NOT NULL DEFAULT 1 CHECK (feasible IN (0,1))
);

CREATE TABLE closure (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  closed_on TEXT NOT NULL,
  accepted_by TEXT NOT NULL,
  final_cost INTEGER NOT NULL,
  final_finish TEXT NOT NULL,
  lessons TEXT NOT NULL
);

CREATE TABLE audit_log (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  action TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT ''
);

-- Activity budget is always derived: duration x rate x allocation + other cost.
CREATE VIEW v_activity_budget AS
SELECT a.id AS activity_id,
       a.other_cost + COALESCE(CAST(ROUND(SUM(a.duration * m.daily_rate * s.allocation / 100.0)) AS INTEGER), 0) AS budget
FROM activities a
LEFT JOIN assignments s ON s.activity_id = a.id
LEFT JOIN team_members m ON m.id = s.member_id
GROUP BY a.id;

-- Scope gate, enforced by the database itself: unapproved requirements cannot enter the WBS.
CREATE TRIGGER trg_wbs_scope_insert BEFORE INSERT ON wbs_items
WHEN NEW.requirement_id IS NOT NULL
 AND (SELECT status FROM requirements WHERE id = NEW.requirement_id) <> 'Approved'
BEGIN SELECT RAISE(ABORT, 'Only approved requirements can be included in the WBS.'); END;

CREATE TRIGGER trg_wbs_scope_update BEFORE UPDATE OF requirement_id ON wbs_items
WHEN NEW.requirement_id IS NOT NULL
 AND (SELECT status FROM requirements WHERE id = NEW.requirement_id) <> 'Approved'
BEGIN SELECT RAISE(ABORT, 'Only approved requirements can be included in the WBS.'); END;

CREATE TRIGGER trg_req_keep_approved BEFORE UPDATE OF status ON requirements
WHEN OLD.status = 'Approved' AND NEW.status <> 'Approved'
 AND EXISTS (SELECT 1 FROM wbs_items WHERE requirement_id = OLD.id)
BEGIN SELECT RAISE(ABORT, 'This requirement already has WBS work and cannot lose its approval.'); END;

CREATE TRIGGER trg_activity_work_package BEFORE INSERT ON activities
WHEN (SELECT kind FROM wbs_items WHERE id = NEW.wbs_id) <> 'Work Package'
BEGIN SELECT RAISE(ABORT, 'Activities can only be attached to a work package.'); END;

CREATE INDEX idx_dep_succ ON dependencies(succ_id);
CREATE INDEX idx_cost_activity ON cost_entries(activity_id);
CREATE INDEX idx_progress_activity ON progress_log(activity_id);
