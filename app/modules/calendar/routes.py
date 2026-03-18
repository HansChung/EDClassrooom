from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from io import BytesIO, StringIO

from flask import Response, render_template, request
from flask_login import current_user, login_required
from odf.opendocument import OpenDocumentSpreadsheet
from odf.table import Table, TableCell, TableRow
from odf.text import P
from openpyxl import Workbook

from app.extensions import db
from app.models import BookingRequest, Classroom
from app.modules.calendar import bp


def _to_ics_dt(value: datetime) -> str:
    utc_time = value.replace(tzinfo=timezone.utc)
    return utc_time.strftime("%Y%m%dT%H%M%SZ")


@bp.route("/")
@login_required
def month_view():
    start = request.args.get("start")
    end = request.args.get("end")
    room_id = request.args.get("room_id", type=int)

    query = db.session.query(BookingRequest).filter(BookingRequest.status.in_(["approved", "pending_approval"]))
    if start:
        query = query.filter(BookingRequest.start_at >= datetime.fromisoformat(start))
    if end:
        query = query.filter(BookingRequest.end_at <= datetime.fromisoformat(end))
    if room_id:
        query = query.filter(BookingRequest.classroom_id == room_id)

    role_names = {role.name for role in current_user.roles}
    if not role_names.intersection({"super_admin", "staff_manager", "workstudy_manager"}):
        query = query.filter(BookingRequest.requester_id == current_user.id)

    bookings = query.order_by(BookingRequest.start_at.asc()).all()
    rooms = db.session.query(Classroom).filter_by(is_active=True).order_by(Classroom.code.asc()).all()
    return render_template("calendar/month.html", bookings=bookings, rooms=rooms)


@bp.route("/export/ics")
@login_required
def export_ics():
    room_id = request.args.get("room_id", type=int)
    query = db.session.query(BookingRequest).filter(BookingRequest.status == "approved")
    if room_id:
        query = query.filter(BookingRequest.classroom_id == room_id)

    role_names = {role.name for role in current_user.roles}
    if not role_names.intersection({"super_admin", "staff_manager", "workstudy_manager"}):
        query = query.filter(BookingRequest.requester_id == current_user.id)

    bookings = query.order_by(BookingRequest.start_at.asc()).all()

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//TKU ETD//Classroom Booking//ZH",
        "CALSCALE:GREGORIAN",
    ]
    for item in bookings:
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:booking-{item.id}@et.tku.edu.tw",
                f"DTSTAMP:{_to_ics_dt(datetime.utcnow())}",
                f"DTSTART:{_to_ics_dt(item.start_at)}",
                f"DTEND:{_to_ics_dt(item.end_at)}",
                f"SUMMARY:{item.classroom.code} {item.title}",
                f"DESCRIPTION:{item.purpose}",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    payload = "\r\n".join(lines)

    return Response(
        payload,
        mimetype="text/calendar",
        headers={"Content-Disposition": "attachment; filename=classroom-bookings.ics"},
    )


@bp.route("/export/csv")
@login_required
def export_csv():
    role_names = {role.name for role in current_user.roles}
    query = db.session.query(BookingRequest)
    if not role_names.intersection({"super_admin", "staff_manager", "workstudy_manager"}):
        query = query.filter(BookingRequest.requester_id == current_user.id)

    start = datetime.utcnow() - timedelta(days=60)
    bookings = query.filter(BookingRequest.start_at >= start).order_by(BookingRequest.start_at.asc()).all()

    csv_io = StringIO()
    writer = csv.writer(csv_io)
    writer.writerow(["id", "classroom", "requester", "title", "start_at", "end_at", "status", "source"])
    for item in bookings:
        writer.writerow(
            [
                item.id,
                item.classroom.code,
                item.requester.display_name,
                item.title,
                item.start_at.isoformat(),
                item.end_at.isoformat(),
                item.status,
                item.source,
            ]
        )

    return Response(
        csv_io.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=classroom-bookings.csv"},
    )


@bp.route("/export/xlsx")
@login_required
def export_xlsx():
    role_names = {role.name for role in current_user.roles}
    query = db.session.query(BookingRequest)
    if not role_names.intersection({"super_admin", "staff_manager", "workstudy_manager"}):
        query = query.filter(BookingRequest.requester_id == current_user.id)

    start = datetime.utcnow() - timedelta(days=60)
    bookings = query.filter(BookingRequest.start_at >= start).order_by(BookingRequest.start_at.asc()).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "bookings"
    ws.append(["id", "classroom", "requester", "title", "start_at", "end_at", "status", "source"])
    for item in bookings:
        ws.append(
            [
                item.id,
                item.classroom.code,
                item.requester.display_name,
                item.title,
                item.start_at.isoformat(),
                item.end_at.isoformat(),
                item.status,
                item.source,
            ]
        )

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return Response(
        output.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=classroom-bookings.xlsx"},
    )


@bp.route("/export/ods")
@login_required
def export_ods():
    role_names = {role.name for role in current_user.roles}
    query = db.session.query(BookingRequest)
    if not role_names.intersection({"super_admin", "staff_manager", "workstudy_manager"}):
        query = query.filter(BookingRequest.requester_id == current_user.id)

    start = datetime.utcnow() - timedelta(days=60)
    bookings = query.filter(BookingRequest.start_at >= start).order_by(BookingRequest.start_at.asc()).all()

    doc = OpenDocumentSpreadsheet()
    table = Table(name="bookings")

    headers = ["id", "classroom", "requester", "title", "start_at", "end_at", "status", "source"]
    header_row = TableRow()
    for title in headers:
        cell = TableCell()
        cell.addElement(P(text=title))
        header_row.addElement(cell)
    table.addElement(header_row)

    for item in bookings:
        row = TableRow()
        values = [
            str(item.id),
            item.classroom.code,
            item.requester.display_name,
            item.title,
            item.start_at.isoformat(),
            item.end_at.isoformat(),
            item.status,
            item.source,
        ]
        for value in values:
            cell = TableCell()
            cell.addElement(P(text=value))
            row.addElement(cell)
        table.addElement(row)

    doc.spreadsheet.addElement(table)
    output = BytesIO()
    doc.save(output)
    output.seek(0)
    return Response(
        output.read(),
        mimetype="application/vnd.oasis.opendocument.spreadsheet",
        headers={"Content-Disposition": "attachment; filename=classroom-bookings.ods"},
    )
