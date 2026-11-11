"""SQLite connection handling, transactions and input validation helpers."""
from __future__ import annotations

import itertools
import re
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from flask import current_app, g

SCHEMA = Path(__file__).with_name("schema.sql")
_savepoints = itertools.count(1)


class ValidationError(Exception):
    """A user-facing rule violation. The message is shown as is."""


def connect(path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect(current_app.config["DB_PATH"])
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


@contextmanager
def tx():
    """Atomic block. Nestable, and any exception undoes everything inside it."""
    conn = db()
    name = f"sp{next(_savepoints)}"
    conn.execute(f"SAVEPOINT {name}")
    try:
        yield conn
    except BaseException:
        conn.execute(f"ROLLBACK TO {name}")
        conn.execute(f"RELEASE {name}")
        raise
    conn.execute(f"RELEASE {name}")


def one(sql, *args):
    return db().execute(sql, args).fetchone()


def rows(sql, *args):
    return db().execute(sql, args).fetchall()


def scalar(sql, *args):
    row = db().execute(sql, args).fetchone()
    return row[0] if row else None


def audit(action, detail=""):
    db().execute("INSERT INTO audit_log(action, detail) VALUES (?, ?)", (action, detail))


def next_code(table: str, prefix: str, width: int) -> str:
    """Next sequential code such as A24 or CR-003."""
    numbers = [int(m.group()) for (c,) in db().execute(f"SELECT code FROM {table}")
               if (m := re.search(r"\d+$", c))]
    return f"{prefix}{max(numbers, default=0) + 1:0{width}d}"


# ---------------------------------------------------------------- validators
def text(data, key, label, required=True, limit=2000) -> str:
    value = (data.get(key) or "").strip()
    if required and not value:
        raise ValidationError(f"{label} is required.")
    if len(value) > limit:
        raise ValidationError(f"{label} must be at most {limit} characters.")
    return value


def integer(data, key, label, low=None, high=None, default=None) -> int:
    raw = str(data.get(key, "") if data.get(key) is not None else "").strip().replace(",", "")
    if raw == "":
        if default is not None:
            return default
        raise ValidationError(f"{label} is required.")
    try:
        value = int(raw)
    except ValueError:
        raise ValidationError(f"{label} must be a whole number.") from None
    if low is not None and value < low:
        raise ValidationError(f"{label} must be at least {low}.")
    if high is not None and value > high:
        raise ValidationError(f"{label} must be at most {high}.")
    return value


def decimal(data, key, label, low=None, high=None) -> float:
    try:
        value = float(str(data.get(key, "")).strip())
    except ValueError:
        raise ValidationError(f"{label} must be a number.") from None
    if value != value or (low is not None and value < low) or (high is not None and value > high):
        raise ValidationError(f"{label} must be between {low} and {high}.")
    return value


def iso_date(data, key, label, required=True) -> str | None:
    raw = (data.get(key) or "").strip()
    if not raw:
        if required:
            raise ValidationError(f"{label} is required.")
        return None
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        raise ValidationError(f"{label} must be a valid date (YYYY-MM-DD).") from None


def choice(data, key, label, options) -> str:
    value = (data.get(key) or "").strip()
    if value not in options:
        raise ValidationError(f"{label} must be one of: {', '.join(options)}.")
    return value


def reference(data, key, label, table, required=True) -> int | None:
    raw = str(data.get(key) or "").strip()
    if not raw:
        if required:
            raise ValidationError(f"{label} is required.")
        return None
    if not raw.isdigit() or not one(f"SELECT 1 FROM {table} WHERE id = ?", int(raw)):
        raise ValidationError(f"{label} does not exist.")
    return int(raw)
