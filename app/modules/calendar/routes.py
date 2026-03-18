from __future__ import annotations

import csv
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
from io import BytesIO, StringIO

from flask import Response, render_template, request
from flask_login import current_user, login_required
from odf.opendocument import OpenDocumentSpreadsheet
from odf.table import Table, TableCell, TableRow
from odf.text import P
from openpyxl import Workbook

from app.extensions import db
from app.models import BookingRequest, Classroom, CourseSchedule
from app.modules.calendar import bp


def _to_ics_dt(value: datetime) -> str:
    utc_time = value.replace(tzinfo=timezone.utc)
    return utc_time.strftime("%Y%m%dT%H%M%SZ")


def _resolve_calendar_window(start: str | None, end: str | None, bookings: list[BookingRequest]) -> tuple[date, date]:
    if start:
        window_start = datetime.fromisoformat(start).date()
    elif bookings:
        window_start = bookings[0].start_at.date()
    else:
        today = date.today()
        window_start = today - timedelta(days=today.weekday())

    if end:
        window_end = datetime.fromisoformat(end).date()
    elif bookings:
        window_end = max(window_start, bookings[-1].start_at.date())
    else:
        window_end = window_start + timedelta(days=6)

    return window_start, window_end


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
    window_start, window_end = _resolve_calendar_window(start, end, bookings)
    rooms = db.session.query(Classroom).filter_by(is_active=True).order_by(Classroom.code.asc()).all()
    schedule_query = db.session.query(CourseSchedule).filter(CourseSchedule.is_active.is_(True))
    if room_id:
        schedule_query = schedule_query.filter(CourseSchedule.classroom_id == room_id)
    schedules = schedule_query.order_by(CourseSchedule.weekday.asc(), CourseSchedule.start_time.asc()).all()

    daily_entries: OrderedDict[str, list[dict]] = OrderedDict()
    for booking in bookings:
        day_key = booking.start_at.strftime("%Y-%m-%d")
        daily_entries.setdefault(day_key, []).append(
            {
                "kind": "booking",
                "start_at": booking.start_at,
                "end_at": booking.end_at,
                "title": booking.title,
                "subtitle": f"{booking.requester.display_name} / {booking.classroom.name} / {booking.source}",
                "status": booking.status,
                "room_code": booking.classroom.code,
                "requester_name": booking.requester.display_name,
            }
        )

    current_date = window_start
    while current_date <= window_end:
        for schedule in schedules:
            if schedule.weekday != current_date.weekday():
                continue
            start_at = datetime.combine(current_date, schedule.start_time)
            end_at = datetime.combine(current_date, schedule.end_time)
            day_key = current_date.strftime("%Y-%m-%d")
            daily_entries.setdefault(day_key, []).append(
                {
                    "kind": "schedule",
                    "start_at": start_at,
                    "end_at": end_at,
                    "title": schedule.course_name,
                    "subtitle": f"{schedule.classroom.name} / {schedule.instructor_name or '未填教師'} / 課表",
                    "status": "approved",
                    "room_code": schedule.classroom.code,
                    "requester_name": schedule.instructor_name or "課程",
                }
            )
        current_date += timedelta(days=1)

    grouped_entries: OrderedDict[str, list[dict]] = OrderedDict()
    for day_key in sorted(daily_entries.keys()):
        grouped_entries[day_key] = sorted(daily_entries[day_key], key=lambda item: item["start_at"])

    anchor_date = window_start

    week_start = anchor_date - timedelta(days=anchor_date.weekday())
    weekly_schedule = []
    for offset in range(7):
        current_day = week_start + timedelta(days=offset)
        day_key = current_day.strftime("%Y-%m-%d")
        current_items = grouped_entries.get(day_key, [])
        weekly_schedule.append(
            {
                "date": current_day,
                "label": current_day.strftime("%m/%d"),
                "weekday": current_day.strftime("%a"),
                "items": current_items,
            }
        )

    return render_template(
        "calendar/month.html",
        bookings=bookings,
        grouped_bookings=grouped_entries.items(),
        rooms=rooms,
        selected_start=start or "",
        selected_end=end or "",
        selected_room_id=room_id,
        weekly_schedule=weekly_schedule,
        week_range_label=f"{week_start.strftime('%Y/%m/%d')} - {(week_start + timedelta(days=6)).strftime('%Y/%m/%d')}",
    )


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
