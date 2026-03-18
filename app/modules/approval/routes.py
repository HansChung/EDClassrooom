from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import AuditLog, BookingApproval, BookingRequest
from app.modules.approval import bp
from app.security import roles_required


@bp.route("/")
@login_required
@roles_required("super_admin", "staff_manager")
def queue():
    bookings = (
        db.session.query(BookingRequest)
        .filter(BookingRequest.status == "pending_approval")
        .order_by(BookingRequest.start_at.asc())
        .all()
    )
    return render_template("approvals/queue.html", bookings=bookings)


@bp.route("/<int:booking_id>/action", methods=["POST"])
@login_required
@roles_required("super_admin", "staff_manager")
def action(booking_id: int):
    booking = db.session.get(BookingRequest, booking_id)
    if booking is None:
        flash("找不到借用申請。", "danger")
        return redirect(url_for("approval.queue"))

    action_name = request.form.get("action", "").strip()
    comment = request.form.get("comment", "").strip() or None
    if action_name not in {"approved", "rejected"}:
        flash("不支援的審核動作。", "danger")
        return redirect(url_for("approval.queue"))

    booking.status = action_name
    db.session.add(
        BookingApproval(
            booking_id=booking.id,
            approver_id=current_user.id,
            action=action_name,
            comment=comment,
        )
    )
    db.session.add(
        AuditLog(
            actor_user_id=current_user.id,
            action=f"booking_{action_name}",
            entity_type="booking_request",
            entity_id=str(booking.id),
            payload={"comment": comment},
        )
    )
    db.session.commit()
    flash("審核結果已更新。", "success")
    return redirect(url_for("approval.queue"))
