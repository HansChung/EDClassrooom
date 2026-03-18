from __future__ import annotations

from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import BookingRequest, Classroom
from app.modules.booking import bp
from app.modules.booking.services import cancel_booking, create_booking, list_visible_bookings_for_role


def _parse_local_datetime(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M")


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
        else:
            flash("借用已送出，待人工核准。", "warning")
        return redirect(url_for("booking.list_bookings"))

    return render_template("bookings/new.html", rooms=rooms)


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
    flash("已取消借用。", "info")
    return redirect(url_for("booking.list_bookings"))
