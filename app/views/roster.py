"""Duty roster module: calendar, manual entry, Excel/CSV import with validation."""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   session, url_for)
from flask_login import current_user

from ..audit import audit
from ..models import DutyRoster, Organization, User, db, now_naive
from ..security import require_role

bp = Blueprint("roster", __name__)

DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y")


def _parse_date(raw: str) -> date | None:
    raw = (raw or "").strip()
    for fmt in DATE_FORMATS:
        try:
            from datetime import datetime
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _org_admin_managers(org_id: int) -> list[User]:
    return (db.session.query(User)
            .filter(User.org_id == org_id, User.role.in_(("ADMIN_MANAGER", "SUPER_ADMIN")),
                    User.active.is_(True)).order_by(User.name).all())


# ------------------------------------------------------------------ view
@bp.get("/roster")
@require_role("ADMIN_MANAGER", "SUPER_ADMIN", "MD_CEO", "HOD")
def roster_view():
    today = now_naive().date()
    month_offset = request.args.get("m", type=int) or 0
    base = today.replace(day=1) + timedelta(days=32 * month_offset)
    start = base.replace(day=1)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    rows = (db.session.query(DutyRoster)
            .filter(DutyRoster.org_id == current_user.org_id,
                    DutyRoster.duty_date >= start, DutyRoster.duty_date <= end)
            .order_by(DutyRoster.duty_date).all())
    by_date = {r.duty_date: r for r in rows}
    days = []
    d = start
    while d <= end:
        days.append({"date": d, "entry": by_date.get(d), "today": d == today})
        d += timedelta(days=1)
    return render_template("roster.html", days=days, month_label=start.strftime("%B %Y"),
                           month_offset=month_offset,
                           admins=_org_admin_managers(current_user.org_id))


# ------------------------------------------------------------------ manual entry
@bp.post("/roster/manual")
@require_role("SUPER_ADMIN", "ADMIN_MANAGER")
def roster_manual():
    if not current_user.is_super:
        abort(403)  # roster management is an admin function
    d = _parse_date(request.form.get("date", ""))
    user_id = request.form.get("user_id", type=int)
    note = (request.form.get("note") or "").strip()
    user = db.session.get(User, user_id) if user_id else None
    if not d:
        flash("Please provide a valid duty date.", "error")
        return redirect(url_for("roster.roster_view"))
    if not user or user.org_id != current_user.org_id or user.role != "ADMIN_MANAGER":
        flash("Please select a valid Admin Manager.", "error")
        return redirect(url_for("roster.roster_view"))
    existing = db.session.query(DutyRoster).filter_by(org_id=current_user.org_id, duty_date=d).first()
    if existing:
        flash(f"A roster entry already exists for {d} ({existing.user.name}). "
              "Edit or delete it first — duplicates are not allowed.", "error")
        return redirect(url_for("roster.roster_view"))
    db.session.add(DutyRoster(org_id=current_user.org_id, duty_date=d, user_id=user.id,
                              source="manual", note=note, created_by=current_user.id))
    audit("ROSTER_MANUAL_ADD", "roster", None, {"date": str(d), "user": user.name})
    db.session.commit()
    flash(f"Roster entry added for {d} — {user.name}.", "success")
    return redirect(url_for("roster.roster_view"))


@bp.post("/roster/<int:rid>/delete")
@require_role("SUPER_ADMIN")
def roster_delete(rid: int):
    r = db.session.get(DutyRoster, rid)
    if not r or r.org_id != current_user.org_id:
        abort(404)
    audit("ROSTER_DELETED", "roster", r.id, {"date": str(r.duty_date), "user": r.user.name})
    db.session.delete(r)
    db.session.commit()
    flash("Roster entry deleted.", "success")
    return redirect(url_for("roster.roster_view"))


@bp.post("/roster/<int:rid>/reassign")
@require_role("SUPER_ADMIN")
def roster_reassign(rid: int):
    r = db.session.get(DutyRoster, rid)
    if not r or r.org_id != current_user.org_id:
        abort(404)
    user = db.session.get(User, request.form.get("user_id", type=int) or 0)
    if not user or user.role != "ADMIN_MANAGER" or user.org_id != current_user.org_id:
        flash("Select a valid Admin Manager.", "error")
        return redirect(url_for("roster.roster_view"))
    old = r.user.name
    r.user_id = user.id
    audit("ROSTER_REASSIGNED", "roster", r.id, {"date": str(r.duty_date), "old": old, "new": user.name})
    db.session.commit()
    flash(f"Duty on {r.duty_date} reassigned to {user.name}.", "success")
    return redirect(url_for("roster.roster_view"))


# ------------------------------------------------------------------ import
@bp.get("/roster/import")
@require_role("SUPER_ADMIN")
def roster_import_form():
    return render_template("roster_import.html")


@bp.post("/roster/import")
@require_role("SUPER_ADMIN")
def roster_import_parse():
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Please choose an Excel (.xlsx) or CSV file.", "error")
        return redirect(url_for("roster.roster_import_form"))
    name = file.filename.lower()
    rows_raw: list[tuple[str, str]] = []
    try:
        if name.endswith(".csv"):
            text = file.read().decode("utf-8-sig", errors="replace")
            for row in csv.DictReader(io.StringIO(text)):
                keys = {(k or "").strip().lower(): v for k, v in row.items()}
                nm = keys.get("name") or keys.get("admin manager") or keys.get("admin_manager") or ""
                dt = keys.get("date") or keys.get("duty date") or keys.get("duty_date") or ""
                note = keys.get("note") or keys.get("duty assignment") or ""
                rows_raw.append(((nm or "").strip(), (dt or "").strip(), (note or "").strip()))
        elif name.endswith(".xlsx"):
            from openpyxl import load_workbook
            wb = load_workbook(file, read_only=True, data_only=True)
            ws = wb.active
            header = [str(c.value or "").strip().lower() for c in next(ws.iter_rows(min_row=1, max_row=1))]

            def col(*candidates):
                for cand in candidates:
                    if cand in header:
                        return header.index(cand)
                return None

            i_name = col("name", "admin manager", "admin_manager")
            i_date = col("date", "duty date", "duty_date")
            i_note = col("note", "duty assignment", "assignment")
            if i_name is None or i_date is None:
                flash('The spreadsheet must contain "Name" and "Date" columns.', "error")
                return redirect(url_for("roster.roster_import_form"))
            for row in ws.iter_rows(min_row=2, values_only=True):
                if row is None:
                    continue
                nm = str(row[i_name] or "").strip()
                dt = str(row[i_date] or "").strip()
                if hasattr(row[i_date], "date"):
                    dt = row[i_date].date().isoformat()
                note = str(row[i_note] or "").strip() if i_note is not None and i_note < len(row) else ""
                rows_raw.append((nm, dt, note))
        else:
            flash("Unsupported file type. Please upload .xlsx or .csv.", "error")
            return redirect(url_for("roster.roster_import_form"))
    except Exception as exc:  # noqa: BLE001
        flash(f"Could not read the file: {str(exc)[:120]}", "error")
        return redirect(url_for("roster.roster_import_form"))

    # ------- validation
    admins = {u.name.lower(): u for u in _org_admin_managers(current_user.org_id)}
    existing_dates = {r.duty_date for r in db.session.query(DutyRoster).filter_by(org_id=current_user.org_id).all()}
    seen_in_file: set[date] = set()
    preview, error_count = [], 0
    for idx, (nm, dt, note) in enumerate(rows_raw, start=2):
        errs = []
        parsed_date = None
        user = None
        if not nm:
            errs.append("Missing Admin Manager name")
        else:
            user = admins.get(nm.lower())
            if not user:
                errs.append(f"Unknown Admin Manager: {nm}")
        if not dt:
            errs.append("Missing date")
        else:
            parsed_date = _parse_date(dt)
            if not parsed_date:
                errs.append(f"Invalid date: {dt}")
            else:
                if parsed_date in seen_in_file:
                    errs.append(f"Duplicate date in file: {parsed_date}")
                if parsed_date in existing_dates:
                    errs.append(f"Date already rostered: {parsed_date}")
        if errs:
            error_count += 1
        else:
            seen_in_file.add(parsed_date)
        preview.append({"row": idx, "name": nm, "date": dt, "note": note, "errors": errs,
                        "ok": not errs})
    session["roster_import_preview"] = preview
    session["roster_import_errors"] = error_count
    return render_template("roster_import_preview.html", preview=preview, error_count=error_count,
                           valid_count=len(preview) - error_count)


@bp.post("/roster/import/confirm")
@require_role("SUPER_ADMIN")
def roster_import_confirm():
    preview = session.get("roster_import_preview")
    if not preview:
        flash("Import preview expired. Please upload the file again.", "error")
        return redirect(url_for("roster.roster_import_form"))
    admins = {u.name.lower(): u for u in _org_admin_managers(current_user.org_id)}
    added, skipped = 0, 0
    existing_dates = {r.duty_date for r in db.session.query(DutyRoster).filter_by(org_id=current_user.org_id).all()}
    for row in preview:
        if row["errors"]:
            skipped += 1
            continue
        d = _parse_date(row["date"])
        user = admins.get(row["name"].lower())
        if not d or not user or d in existing_dates:
            skipped += 1
            continue
        db.session.add(DutyRoster(org_id=current_user.org_id, duty_date=d, user_id=user.id,
                                  source="import", note=row.get("note") or None,
                                  created_by=current_user.id))
        existing_dates.add(d)
        added += 1
    audit("ROSTER_IMPORTED", "roster", None, {"added": added, "skipped": skipped})
    db.session.commit()
    session.pop("roster_import_preview", None)
    flash(f"Import complete: {added} entries added, {skipped} skipped.", "success")
    return redirect(url_for("roster.roster_view"))
