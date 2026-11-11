"""Pure calculation engines: working calendar, critical path, forecast, EVM.

No database or web code lives here, so every formula can be unit tested directly.
Time is measured in working-day offsets from the project start. An activity
occupies the half-open range [start, finish).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import date, timedelta


class ScheduleError(Exception):
    """The activity network cannot be scheduled (for example a dependency loop)."""


# ---------------------------------------------------------------- calendar
class Calendar:
    """Monday to Friday calendar anchored on the project start date."""

    def __init__(self, start: date):
        self.start = self.roll_forward(start)

    @staticmethod
    def roll_forward(d: date) -> date:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        return d

    def date_of(self, offset: int) -> date:
        weeks, days = divmod(offset, 5)
        d = self.start + timedelta(weeks=weeks)
        for _ in range(days):
            d = self.roll_forward(d + timedelta(days=1))
        return d

    def offset_of(self, d: date) -> int:
        """Offset of a date. A weekend date maps to the following Monday."""
        d = self.roll_forward(d)
        sign = 1
        a, b = self.start, d
        if d < self.start:
            sign, a, b = -1, d, self.start
        weeks, rem = divmod((b - a).days, 7)
        count = weeks * 5
        for i in range(rem):
            if (a + timedelta(days=i)).weekday() < 5:
                count += 1
        return sign * count

    def data_offset(self, status: date) -> int:
        """Working days fully elapsed by the end of the status date."""
        if status < self.start:
            return 0
        return self.offset_of(status) + (1 if status.weekday() < 5 else 0)

    def finish_date(self, finish_offset: int) -> date:
        return self.date_of(finish_offset - 1)


def add_workdays(d: date, n: int) -> date:
    """Date n working days after d."""
    return Calendar(d).date_of(n)


# ---------------------------------------------------------------- network
@dataclass(frozen=True)
class Link:
    pred: str
    type: str = "FS"
    lag: int = 0


@dataclass
class Task:
    code: str
    duration: int
    preds: list[Link] = field(default_factory=list)
    actual_start: int | None = None
    actual_finish: int | None = None  # exclusive offset
    pct: int = 0
    remaining: int | None = None

    @property
    def finished(self) -> bool:
        return self.actual_finish is not None

    @property
    def started(self) -> bool:
        return self.actual_start is not None

    @property
    def remaining_work(self) -> int:
        if self.remaining is not None:
            return self.remaining
        return max(1, math.ceil(self.duration * (100 - self.pct) / 100))


@dataclass
class Timing:
    es: int
    ef: int
    ls: int = 0
    lf: int = 0

    @property
    def float(self) -> int:
        return self.ls - self.es

    @property
    def critical(self) -> bool:
        return self.float == 0


@dataclass
class Forecast:
    start: int
    finish: int
    slip: int
    own_slip: int
    driver: str | None


def topo_order(tasks: list[Task]) -> list[Task]:
    by_code = {t.code: t for t in tasks}
    indegree = {t.code: 0 for t in tasks}
    successors: dict[str, list[str]] = {t.code: [] for t in tasks}
    for t in tasks:
        for link in t.preds:
            if link.pred not in by_code:
                raise ScheduleError(f"{t.code} depends on unknown activity {link.pred}.")
            indegree[t.code] += 1
            successors[link.pred].append(t.code)
    ready = [c for c, n in indegree.items() if n == 0]
    order = []
    while ready:
        code = ready.pop(0)
        order.append(by_code[code])
        for s in successors[code]:
            indegree[s] -= 1
            if indegree[s] == 0:
                ready.append(s)
    if len(order) != len(tasks):
        stuck = sorted(c for c, n in indegree.items() if n > 0)
        raise ScheduleError("Dependency loop detected among: " + ", ".join(stuck) + ".")
    return order


def _bounds(task: Task, starts: dict[str, int], finishes: dict[str, int]):
    """Earliest start and finish allowed by the task's dependencies."""
    min_start, min_finish, driver, best = 0, 0, None, None
    for link in task.preds:
        p_start, p_finish = starts[link.pred], finishes[link.pred]
        if link.type == "FS":
            value = p_finish + link.lag
            min_start = max(min_start, value)
            effective = value
        elif link.type == "SS":
            value = p_start + link.lag
            min_start = max(min_start, value)
            effective = value
        elif link.type == "FF":
            value = p_finish + link.lag
            min_finish = max(min_finish, value)
            effective = value - task.duration
        else:  # SF
            value = p_start + link.lag
            min_finish = max(min_finish, value)
            effective = value - task.duration
        if best is None or effective > best:
            best, driver = effective, link.pred
    return min_start, min_finish, driver


def cpm(tasks: list[Task]) -> tuple[dict[str, Timing], int]:
    """Forward and backward pass. Returns timings and the project finish offset."""
    order = topo_order(tasks)
    starts: dict[str, int] = {}
    finishes: dict[str, int] = {}
    for t in order:
        min_start, min_finish, _ = _bounds(t, starts, finishes)
        starts[t.code] = max(0, min_start, min_finish - t.duration)
        finishes[t.code] = starts[t.code] + t.duration
    project_finish = max(finishes.values(), default=0)

    by_code = {t.code: t for t in tasks}
    late_finish = {t.code: project_finish for t in tasks}
    late_start: dict[str, int] = {}
    for t in reversed(order):
        late_start[t.code] = late_finish[t.code] - t.duration
        for link in t.preds:
            duration = by_code[link.pred].duration
            if link.type == "FS":
                limit = late_start[t.code] - link.lag
            elif link.type == "SS":
                limit = late_start[t.code] - link.lag + duration
            elif link.type == "FF":
                limit = late_finish[t.code] - link.lag
            else:  # SF
                limit = late_finish[t.code] - link.lag + duration
            late_finish[link.pred] = min(late_finish[link.pred], limit)
    timings = {
        c: Timing(starts[c], finishes[c], late_start[c], late_finish[c]) for c in starts
    }
    return timings, project_finish


def forecast(tasks: list[Task], data_offset: int, plan: dict[str, Timing]):
    """Roll actual progress through the network. Returns forecasts and finish offset."""
    starts: dict[str, int] = {}
    finishes: dict[str, int] = {}
    result: dict[str, Forecast] = {}
    for t in topo_order(tasks):
        min_start, min_finish, driver = _bounds(t, starts, finishes)
        expected_finish = max(0, min_start, min_finish - t.duration) + t.duration
        if t.finished:
            start, finish = t.actual_start, t.actual_finish
        elif t.started:
            start = t.actual_start
            finish = max(data_offset + t.remaining_work, min_finish)
        else:
            start = max(data_offset, min_start, min_finish - t.duration)
            finish = start + t.duration
        starts[t.code], finishes[t.code] = start, finish
        slip = finish - plan[t.code].ef
        own = min(max(0, finish - expected_finish), max(slip, 0))
        result[t.code] = Forecast(start, finish, slip, own, driver)
    return result, max(finishes.values(), default=0)


def delay_impact(tasks: list[Task], code: str, days: int) -> dict:
    """Effect of one activity running `days` longer on the planned network."""
    base, base_finish = cpm(tasks)
    changed = [replace(t, duration=t.duration + days) if t.code == code else t for t in tasks]
    new, new_finish = cpm(changed)
    shifted = {c: new[c].ef - base[c].ef for c in new if c != code and new[c].ef > base[c].ef}
    return {"shifted": shifted, "finish_shift": new_finish - base_finish,
            "absorbed": days - (new_finish - base_finish)}


def what_if(tasks: list[Task], data_offset: int, code: str, days: int) -> dict:
    """Effect of a further delay on the current forecast."""
    plan, _ = cpm(tasks)
    base, base_finish = forecast(tasks, data_offset, plan)
    changed = []
    for t in tasks:
        if t.code != code:
            changed.append(t)
        elif t.finished:
            raise ScheduleError(f"{code} is already finished and cannot be delayed.")
        elif t.started:
            changed.append(replace(t, remaining=t.remaining_work + days))
        else:
            changed.append(replace(t, duration=t.duration + days))
    new, new_finish = forecast(changed, data_offset, plan)
    shifted = {c: new[c].finish - base[c].finish for c in new
               if c != code and new[c].finish > base[c].finish}
    return {"shifted": shifted, "finish_before": base_finish, "finish_after": new_finish,
            "finish_shift": new_finish - base_finish}


# ---------------------------------------------------------------- earned value
def planned_fraction(start: int, finish: int, data_offset: int) -> float:
    if finish <= start:
        return 1.0 if data_offset >= finish else 0.0
    return min(1.0, max(0.0, (data_offset - start) / (finish - start)))


@dataclass
class Evm:
    bac: float
    pv: float
    ev: float
    ac: float

    @property
    def cv(self): return self.ev - self.ac
    @property
    def sv(self): return self.ev - self.pv
    @property
    def cpi(self): return self.ev / self.ac if self.ac > 0 else None
    @property
    def spi(self): return self.ev / self.pv if self.pv > 0 else None
    @property
    def eac(self):
        return self.bac / self.cpi if self.cpi else self.bac
    @property
    def etc(self): return max(0.0, self.eac - self.ac)
    @property
    def vac(self): return self.bac - self.eac
    @property
    def tcpi(self):
        return (self.bac - self.ev) / (self.bac - self.ac) if self.bac > self.ac else None
    @property
    def pct_complete(self): return 100 * self.ev / self.bac if self.bac else 0.0
    @property
    def pct_planned(self): return 100 * self.pv / self.bac if self.bac else 0.0


def performance_alerts(evm: Evm, limits: dict, budget: float, finish_slip: int) -> list[dict]:
    """Compare performance against thresholds. finish_slip = forecast minus deadline."""
    alerts = []

    def add(level, title, detail):
        alerts.append({"level": level, "title": title, "detail": detail})

    for name, value, warn, crit, meaning in (
        ("CPI", evm.cpi, limits["cpi_warn"], limits["cpi_crit"], "cost efficiency"),
        ("SPI", evm.spi, limits["spi_warn"], limits["spi_crit"], "schedule efficiency"),
    ):
        if value is None:
            continue
        if value < crit:
            add("critical", f"{name} {value:.2f} is below the critical limit {crit:.2f}",
                f"{meaning.capitalize()} needs corrective action.")
        elif value < warn:
            add("warning", f"{name} {value:.2f} is below the warning limit {warn:.2f}",
                f"{meaning.capitalize()} is under target.")
    if evm.ac > budget:
        add("critical", "Actual cost exceeds the approved budget",
            f"Overspent by PKR {evm.ac - budget:,.0f}.")
    elif budget and 100 * evm.ac / budget >= limits["budget_warn_pct"]:
        add("warning", f"{100 * evm.ac / budget:.0f}% of the approved budget is spent",
            f"Warning limit is {limits['budget_warn_pct']:.0f}%.")
    if evm.eac > budget:
        add("critical", "Forecast cost overrun",
            f"EAC PKR {evm.eac:,.0f} exceeds the approved budget by PKR {evm.eac - budget:,.0f}.")
    if finish_slip > limits["slip_warn_days"]:
        add("critical", f"Forecast finish is {finish_slip} working days past the deadline",
            f"Allowed deviation is {limits['slip_warn_days']} working days.")
    elif finish_slip > 0:
        add("warning", f"Forecast finish is {finish_slip} working days past the deadline",
            "Within tolerance, but recovery is needed.")
    return alerts
