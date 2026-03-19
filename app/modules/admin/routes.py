from __future__ import annotations

import csv
from datetime import datetime
from io import StringIO

from flask import Response, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import BookingRequest, Classroom, ClassroomBlock, CourseSchedule, Role, SystemRule, User
from app.modules.admin import bp
from app.modules.booking.services import create_booking
from app.modules.notifications.services import create_notification
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
    blocks = (
        db.session.query(ClassroomBlock)
        .join(Classroom)
        .order_by(ClassroomBlock.start_at.asc(), Classroom.code.asc())
        .all()
    )
    return render_template(
        "admin/dashboard.html",
        rooms=rooms,
        rules=rules,
        users=users,
        schedules=schedules,
        blocks=blocks,
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


@bp.route("/schedules/import", methods=["POST"])
@login_required
@roles_required("super_admin", "staff_manager")
def import_schedules():
    file = request.files.get("schedule_file")
    if file is None or not file.filename:
        flash("請選擇要匯入的 CSV 檔案。", "danger")
        return redirect(url_for("admin.dashboard"))

    try:
        content = file.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        flash("CSV 檔案編碼需為 UTF-8。", "danger")
        return redirect(url_for("admin.dashboard"))

    reader = csv.DictReader(StringIO(content))
    required_columns = {
        "classroom_code",
        "course_name",
        "instructor_name",
        "weekday",
        "start_time",
        "end_time",
        "semester_label",
        "is_active",
    }
    if not reader.fieldnames or not required_columns.issubset(set(reader.fieldnames)):
        flash("CSV 欄位不足，需包含 classroom_code, course_name, instructor_name, weekday, start_time, end_time, semester_label, is_active。", "danger")
        return redirect(url_for("admin.dashboard"))

    imported = 0
    skipped = 0
    for row in reader:
        try:
            classroom_code = (row.get("classroom_code") or "").strip().upper()
            classroom = db.session.query(Classroom).filter_by(code=classroom_code).first()
            if classroom is None:
                skipped += 1
                continue

            course_name = (row.get("course_name") or "").strip()
            if not course_name:
                skipped += 1
                continue

            weekday = int((row.get("weekday") or "0").strip())
            if weekday < 0 or weekday > 6:
                skipped += 1
                continue

            start_time = datetime.strptime((row.get("start_time") or "").strip(), "%H:%M").time()
            end_time = datetime.strptime((row.get("end_time") or "").strip(), "%H:%M").time()
            if start_time >= end_time:
                skipped += 1
                continue

            schedule = CourseSchedule(
                classroom_id=classroom.id,
                course_name=course_name,
                instructor_name=(row.get("instructor_name") or "").strip() or None,
                weekday=weekday,
                start_time=start_time,
                end_time=end_time,
                semester_label=(row.get("semester_label") or "").strip() or "current",
                is_active=(row.get("is_active") or "").strip().lower() in {"1", "true", "yes", "y"},
            )
            db.session.add(schedule)
            imported += 1
        except (TypeError, ValueError):
            skipped += 1

    db.session.commit()
    flash(f"課表匯入完成，新增 {imported} 筆，略過 {skipped} 筆。", "success")
    return redirect(url_for("admin.dashboard"))


@bp.route("/schedules/template.csv")
@login_required
@roles_required("super_admin", "staff_manager")
def download_schedule_template():
    payload = (
        "classroom_code,course_name,instructor_name,weekday,start_time,end_time,semester_label,is_active\n"
        "L105,資料結構,王老師,0,09:00,11:00,114-2,true\n"
        "ED202,教學設計,陳老師,2,13:00,15:00,114-2,true\n"
    )
    return Response(
        payload,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=course-schedule-template.csv"},
    )


@bp.route("/blocks", methods=["POST"])
@login_required
@roles_required("super_admin", "staff_manager")
def upsert_block():
    classroom = db.session.get(Classroom, int(request.form["classroom_id"]))
    if classroom is None:
        flash("找不到教室。", "danger")
        return redirect(url_for("admin.dashboard"))

    start_at = datetime.strptime(request.form["start_at"], "%Y-%m-%dT%H:%M")
    end_at = datetime.strptime(request.form["end_at"], "%Y-%m-%dT%H:%M")
    if start_at >= end_at:
        flash("停用結束時間需晚於開始時間。", "danger")
        return redirect(url_for("admin.dashboard"))

    block = ClassroomBlock(
        classroom_id=classroom.id,
        title=request.form["title"].strip(),
        reason=request.form.get("reason", "").strip() or None,
        block_type=request.form.get("block_type", "maintenance").strip() or "maintenance",
        start_at=start_at,
        end_at=end_at,
        is_active=request.form.get("is_active") == "on",
    )
    db.session.add(block)
    impacted_bookings = (
        db.session.query(BookingRequest)
        .filter(
            BookingRequest.classroom_id == classroom.id,
            BookingRequest.status.in_(["approved", "pending_approval"]),
            BookingRequest.start_at < end_at,
            BookingRequest.end_at > start_at,
        )
        .all()
    )
    for booking in impacted_bookings:
        create_notification(
            user_id=booking.requester_id,
            title="借用時段受到停用影響",
            body=f"{classroom.code} {booking.title} 與停用時段《{block.title}》重疊，請儘快確認。",
            link=url_for("booking.list_bookings"),
        )
    db.session.commit()
    flash("教室停用時段已建立。", "success")
    return redirect(url_for("admin.dashboard"))


@bp.route("/blocks/<int:block_id>/delete", methods=["POST"])
@login_required
@roles_required("super_admin", "staff_manager")
def delete_block(block_id: int):
    block = db.session.get(ClassroomBlock, block_id)
    if block is None:
        flash("找不到停用時段。", "danger")
        return redirect(url_for("admin.dashboard"))

    db.session.delete(block)
    db.session.commit()
    flash("停用時段已刪除。", "info")
    return redirect(url_for("admin.dashboard"))
