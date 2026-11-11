"""Smart Healthcare Software Project Management System."""
from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import date
from pathlib import Path

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for

from . import db as database
from .engine import ScheduleError
from .seed import seed


def _fmt_date(value):
    if not value:
        return "-"
    if isinstance(value, str):
        value = date.fromisoformat(value)
    return value.strftime("%d %b %Y")


def _fmt_money(value):
    return "-" if value is None else f"PKR {value:,.0f}"


def _fmt_index(value):
    return "n/a" if value is None else f"{value:.2f}"


def create_app(db_path, testing=False) -> Flask:
    app = Flask(__name__)
    app.config.update(DB_PATH=str(db_path), TESTING=testing, SECRET_KEY=secrets.token_hex(32))
    if not Path(db_path).exists():
        seed(db_path)

    app.teardown_appcontext(database.close_db)
    app.jinja_env.filters.update(dmy=_fmt_date, money=_fmt_money, idx=_fmt_index)

    def csrf_token():
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(16)
        return session["csrf"]

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def guard():
        if request.method != "POST":
            return None
        expected = session.get("csrf")
        if not testing and (not expected or request.form.get("_csrf") != expected):
            abort(400, "Your session expired. Reload the page and try again.")
        closed = database.one("SELECT status FROM project")["status"] == "Closed"
        if closed and request.endpoint != "reset":
            flash("The project is closed and is now read-only.", "error")
            return redirect(url_for("closure_page"))
        return None

    @app.context_processor
    def layout_data():
        from .services import project
        return {"project_header": project()}

    @app.errorhandler(database.ValidationError)
    @app.errorhandler(ScheduleError)
    @app.errorhandler(sqlite3.IntegrityError)
    def rule_broken(exc):
        flash(str(exc), "error")
        return redirect(request.referrer or url_for("dashboard_page"))

    @app.errorhandler(404)
    def not_found(_exc):
        return render_template("error.html", title="Page not found",
                               message="That record or page does not exist."), 404

    @app.errorhandler(400)
    def bad_request(exc):
        return render_template("error.html", title="Request not accepted", message=exc.description), 400

    @app.errorhandler(500)
    def server_error(_exc):
        return render_template("error.html", title="Something went wrong",
                               message="The action was cancelled and your data was not changed."), 500

    from .views import register
    register(app)
    return app


def reset_database(path):
    """Replace the database with fresh sample data."""
    if os.path.exists(path):
        os.remove(path)
    seed(path)
