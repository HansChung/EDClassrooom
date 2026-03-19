from __future__ import annotations

from datetime import datetime

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import BookingRequest, Classroom
from app.modules.booking import bp
from app.modules.notifications.services import create_notification, create_notifications_for_roles
from app.modules.booking.services import (
    cancel_booking,
    create_booking,
    list_room_availability,
    list_visible_bookings_for_role,
)


def _parse_local_datetime(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M")


def _format_slot(slot_start: datetime, slot_end: datetime) -> str:
    return f"{slot_start:%H:%M} - {slot_end:%H:%M}"


def _format_slot_duration(slot_start: datetime, slot_end: datetime) -> str:
    duration_minutes = int((slot_end - slot_start).total_seconds() // 60)
    hours, minutes = divmod(duration_minutes, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


@bp.route("/")
@login_required
def list_bookings():
    role_names = {role.name for role in current_user.roles}
    bookings = list_visible_bookings_for_role(role_names, current_user.id)
    return render_template("bookings/list.html", bookings=bookings)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_booking():
    rooms = (
        db.session.query(Classroom)
        .filter(Classroom.is_active.is_(True), Classroom.is_online_bookable.is_(True))
        .order_by(Classroom.code.asc())
        .all()
    )
    if request.method == "POST":
        classroom = db.session.get(Classroom, int(request.form["classroom_id"]))
        if classroom is None:
            flash("找不到教室。", "danger")
            return redirect(url_for("booking.new_booking"))

        try:
            booking = create_booking(
                requester=current_user,
                classroom=classroom,
                title=request.form["title"].strip(),
                purpose=request.form["purpose"].strip(),
                attendee_count=int(request.form["attendee_count"]),
                start_at=_parse_local_datetime(request.form["start_at"]),
                end_at=_parse_local_datetime(request.form["end_at"]),
                source="online",
            )
        except ValueError as exc:
            flash(str(exc), "danger")
            return render_template("bookings/new.html", rooms=rooms)

        if booking.status == "approved":
            flash("借用已自動核准。", "success")
            create_notification(
                user_id=current_user.id,
                title="借用已自動核准",
                body=f"{classroom.code} {booking.title} 已自動核准。",
                link=url_for("booking.list_bookings"),
            )
        else:
            flash("借用已送出，待人工核准。", "warning")
            create_notification(
                user_id=current_user.id,
                title="借用已送出",
                body=f"{classroom.code} {booking.title} 已送出，待人工核准。",
                link=url_for("booking.list_bookings"),
            )
            create_notifications_for_roles(
                role_names={"super_admin", "staff_manager"},
                title="有新的借用待審核",
                body=f"{current_user.display_name} 送出 {classroom.code} {booking.title} 借用申請。",
                link=url_for("approval.queue"),
            )
        db.session.commit()
        return redirect(url_for("booking.list_bookings"))

    return render_template("bookings/new.html", rooms=rooms)


@bp.route("/availability")
@login_required
def availability():
    classroom_id = request.args.get("classroom_id", type=int)
    target_date_raw = request.args.get("date", "").strip()

    if not classroom_id or not target_date_raw:
        return jsonify({"error": "請提供教室與日期。"}), 400

    classroom = db.session.get(Classroom, classroom_id)
    if classroom is None or not classroom.is_active or not classroom.is_online_bookable:
        return jsonify({"error": "找不到可借用教室。"}), 404

    try:
        target_date = datetime.strptime(target_date_raw, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "日期格式不正確。"}), 400

    occupied_slots, available_slots = list_room_availability(
        classroom_id=classroom.id,
        target_date=target_date,
    )
    return jsonify(
        {
            "classroom": {
                "id": classroom.id,
                "code": classroom.code,
                "name": classroom.name,
            },
            "date": target_date.isoformat(),
            "window": {
                "start": "08:00",
                "end": "22:00",
            },
            "occupied_slots": [
                {
                    "start": slot.start_at.isoformat(),
                    "end": slot.end_at.isoformat(),
                    "label": _format_slot(slot.start_at, slot.end_at),
                    "duration": _format_slot_duration(slot.start_at, slot.end_at),
                    "source": slot.source,
                    "title": slot.label,
                }
                for slot in occupied_slots
            ],
            "available_slots": [
                {
                    "start": slot.start_at.isoformat(),
                    "end": slot.end_at.isoformat(),
                    "label": _format_slot(slot.start_at, slot.end_at),
                    "duration": _format_slot_duration(slot.start_at, slot.end_at),
                    "source": slot.source,
                    "title": slot.label,
                }
                for slot in available_slots
            ],
        }
    )


@bp.route("/<int:booking_id>/cancel", methods=["POST"])
@login_required
def cancel(booking_id: int):
    booking = db.session.get(BookingRequest, booking_id)
    if booking is None:
        flash("找不到借用單。", "danger")
        return redirect(url_for("booking.list_bookings"))

    is_owner = booking.requester_id == current_user.id
    has_manager_role = current_user.has_any_role({"super_admin", "staff_manager"})
    if not is_owner and not has_manager_role:
        flash("你沒有取消此借用單的權限。", "danger")
        return redirect(url_for("booking.list_bookings"))

    cancel_booking(
        booking=booking,
        actor=current_user,
        reason=request.form.get("reason", "使用者取消").strip() or "使用者取消",
    )
    create_notification(
        user_id=booking.requester_id,
        title="借用已取消",
        body=f"{booking.classroom.code} {booking.title} 已取消。",
        link=url_for("booking.list_bookings"),
    )
    db.session.commit()
    flash("已取消借用。", "info")
    return redirect(url_for("booking.list_bookings"))
