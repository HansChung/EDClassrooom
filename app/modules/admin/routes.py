from __future__ import annotations

from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Classroom, CourseSchedule, Role, SystemRule, User
from app.modules.admin import bp
from app.modules.booking.services import create_booking
from app.security import roles_required


@bp.route("/")
@login_required
@roles_required("super_admin", "staff_manager", "workstudy_manager")
def dashboard():
    rooms = db.session.query(Classroom).order_by(Classroom.code.asc()).all()
    rules = db.session.query(SystemRule).order_by(SystemRule.key.asc()).all()
    users = db.session.query(User).order_by(User.display_name.asc()).limit(100).all()
    schedules = (
        db.session.query(CourseSchedule)
        .join(Classroom)
        .order_by(Classroom.code.asc(), CourseSchedule.weekday.asc(), CourseSchedule.start_time.asc())
        .all()
    )
    return render_template(
        "admin/dashboard.html",
        rooms=rooms,
        rules=rules,
        users=users,
        schedules=schedules,
    )


@bp.route("/classrooms", methods=["POST"])
@login_required
@roles_required("super_admin", "staff_manager")
def upsert_classroom():
    code = request.form["code"].strip().upper()
    room = db.session.query(Classroom).filter_by(code=code).first()
    if room is None:
        room = Classroom(code=code)
        db.session.add(room)

    room.name = request.form["name"].strip()
    room.location = request.form["location"].strip()
    room.capacity = int(request.form["capacity"])
    room.is_online_bookable = request.form.get("is_online_bookable") == "on"
    room.note = request.form.get("note", "").strip() or None
    db.session.commit()
    flash("教室資料已更新。", "success")
    return redirect(url_for("admin.dashboard"))


@bp.route("/rules", methods=["POST"])
@login_required
@roles_required("super_admin", "staff_manager")
def upsert_rule():
    key = request.form["key"].strip()
    value = request.form["value"].strip()
    description = request.form["description"].strip()

    rule = db.session.query(SystemRule).filter_by(key=key).first()
    if rule is None:
        rule = SystemRule(key=key, value=value, description=description)
        db.session.add(rule)
    else:
        rule.value = value
        rule.description = description
    db.session.commit()
    flash("規則已更新。", "success")
    return redirect(url_for("admin.dashboard"))


@bp.route("/users/<int:user_id>/roles", methods=["POST"])
@login_required
@roles_required("super_admin")
def update_user_roles(user_id: int):
    user = db.session.get(User, user_id)
    if user is None:
        flash("找不到使用者。", "danger")
        return redirect(url_for("admin.dashboard"))

    selected_roles = request.form.getlist("roles")
    user.roles = db.session.query(Role).filter(Role.name.in_(selected_roles)).all()
    db.session.commit()
    flash("使用者角色已更新。", "success")
    return redirect(url_for("admin.dashboard"))


@bp.route("/manual-booking", methods=["POST"])
@login_required
@roles_required("super_admin", "staff_manager", "workstudy_manager")
def manual_booking():
    requester = db.session.get(User, int(request.form["requester_id"]))
    classroom = db.session.get(Classroom, int(request.form["classroom_id"]))
    if requester is None or classroom is None:
        flash("借用對象或教室不存在。", "danger")
        return redirect(url_for("admin.dashboard"))

    start_at = datetime.strptime(request.form["start_at"], "%Y-%m-%dT%H:%M")
    end_at = datetime.strptime(request.form["end_at"], "%Y-%m-%dT%H:%M")

    try:
        booking = create_booking(
            requester=requester,
            classroom=classroom,
            title=request.form["title"].strip(),
            purpose=request.form["purpose"].strip(),
            attendee_count=int(request.form["attendee_count"]),
            start_at=start_at,
            end_at=end_at,
            source="manual",
        )
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("admin.dashboard"))

    if classroom.is_online_bookable:
        flash(f"人工登記完成（單號 #{booking.id}）。", "success")
    else:
        flash(f"已為不可線上借用教室完成人工登記（單號 #{booking.id}）。", "success")
    return redirect(url_for("admin.dashboard"))


@bp.route("/schedules", methods=["POST"])
@login_required
@roles_required("super_admin", "staff_manager")
def upsert_schedule():
    classroom = db.session.get(Classroom, int(request.form["classroom_id"]))
    if classroom is None:
        flash("找不到教室。", "danger")
        return redirect(url_for("admin.dashboard"))

    schedule_id = request.form.get("schedule_id", type=int)
    schedule = db.session.get(CourseSchedule, schedule_id) if schedule_id else None
    if schedule is None:
        schedule = CourseSchedule(classroom_id=classroom.id)
        db.session.add(schedule)

    start_time = datetime.strptime(request.form["start_time"], "%H:%M").time()
    end_time = datetime.strptime(request.form["end_time"], "%H:%M").time()
    if start_time >= end_time:
        flash("課表結束時間需晚於開始時間。", "danger")
        return redirect(url_for("admin.dashboard"))

    schedule.classroom_id = classroom.id
    schedule.course_name = request.form["course_name"].strip()
    schedule.instructor_name = request.form.get("instructor_name", "").strip() or None
    schedule.weekday = int(request.form["weekday"])
    schedule.start_time = start_time
    schedule.end_time = end_time
    schedule.semester_label = request.form.get("semester_label", "").strip() or "current"
    schedule.is_active = request.form.get("is_active") == "on"
    db.session.commit()
    flash("課表已更新。", "success")
    return redirect(url_for("admin.dashboard"))


@bp.route("/schedules/<int:schedule_id>/delete", methods=["POST"])
@login_required
@roles_required("super_admin", "staff_manager")
def delete_schedule(schedule_id: int):
    schedule = db.session.get(CourseSchedule, schedule_id)
    if schedule is None:
        flash("找不到課表。", "danger")
        return redirect(url_for("admin.dashboard"))

    db.session.delete(schedule)
    db.session.commit()
    flash("課表已刪除。", "info")
    return redirect(url_for("admin.dashboard"))
