from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from sqlalchemy import and_, or_

from app.extensions import db
from app.models import (
    AuditLog,
    BookingPeriod,
    BookingRequest,
    Classroom,
    ClassroomAvailabilityOverride,
    ClassroomBlock,
    CourseSchedule,
    SystemRule,
    User,
)


DEFAULT_PERIOD_SLOTS = [
    ("01", time(hour=8, minute=10), time(hour=9, minute=0)),
    ("02", time(hour=9, minute=10), time(hour=10, minute=0)),
    ("03", time(hour=10, minute=10), time(hour=11, minute=0)),
    ("04", time(hour=11, minute=10), time(hour=12, minute=0)),
    ("05", time(hour=12, minute=10), time(hour=13, minute=0)),
    ("06", time(hour=13, minute=10), time(hour=14, minute=0)),
    ("07", time(hour=14, minute=10), time(hour=15, minute=0)),
    ("08", time(hour=15, minute=10), time(hour=16, minute=0)),
    ("09", time(hour=16, minute=10), time(hour=17, minute=0)),
    ("10", time(hour=17, minute=10), time(hour=18, minute=0)),
    ("11", time(hour=18, minute=20), time(hour=19, minute=10)),
    ("12", time(hour=19, minute=20), time(hour=20, minute=10)),
    ("13", time(hour=20, minute=20), time(hour=21, minute=10)),
    ("14", time(hour=21, minute=20), time(hour=22, minute=10)),
]


@dataclass
class BookingValidationResult:
    ok: bool
    risk_level: str = "low"
    reason: str = ""


@dataclass
class TimeSlot:
    start_at: datetime
    end_at: datetime
    source: str = "booking"
    label: str = ""


@dataclass
class BookingWindow:
    start_time: time
    end_time: time
    is_closed: bool = False
    title: str = ""
    note: str = ""


@dataclass
class RoomGridCell:
    period_code: str
    start_at: datetime
    end_at: datetime
    status: str
    label: str = ""
    title: str = ""


def get_booking_periods() -> list[tuple[str, time, time]]:
    periods = (
        db.session.query(BookingPeriod)
        .filter(BookingPeriod.is_active.is_(True))
        .order_by(BookingPeriod.sort_order.asc(), BookingPeriod.code.asc())
        .all()
    )
    if periods:
        return [(period.code, period.start_time, period.end_time) for period in periods]
    return DEFAULT_PERIOD_SLOTS


def _get_room_bookings_for_window(
    *,
    classroom_id: int,
    start_at: datetime,
    end_at: datetime,
) -> list[BookingRequest]:
    return (
        db.session.query(BookingRequest)
        .filter(
            BookingRequest.classroom_id == classroom_id,
            BookingRequest.status.in_(["approved", "pending", "pending_approval"]),
            and_(BookingRequest.start_at < end_at, BookingRequest.end_at > start_at),
        )
        .order_by(BookingRequest.start_at.asc())
        .all()
    )


def _get_availability_override(*, classroom: Classroom, target_date: date) -> ClassroomAvailabilityOverride | None:
    overrides = (
        db.session.query(ClassroomAvailabilityOverride)
        .filter(
            ClassroomAvailabilityOverride.is_active.is_(True),
            ClassroomAvailabilityOverride.override_date == target_date,
            or_(
                ClassroomAvailabilityOverride.classroom_id == classroom.id,
                and_(
                    ClassroomAvailabilityOverride.classroom_id.is_(None),
                    ClassroomAvailabilityOverride.location == classroom.location,
                ),
            ),
        )
        .order_by(ClassroomAvailabilityOverride.classroom_id.is_(None).asc(), ClassroomAvailabilityOverride.id.desc())
        .all()
    )
    return overrides[0] if overrides else None


def get_classroom_booking_window(classroom: Classroom, target_date: date | None = None) -> BookingWindow:
    base_window = BookingWindow(
        start_time=classroom.booking_start_time or time(hour=8),
        end_time=classroom.booking_end_time or time(hour=22),
    )
    if target_date is None:
        return base_window

    override = _get_availability_override(classroom=classroom, target_date=target_date)
    if override is None:
        return base_window
    if override.is_closed:
        return BookingWindow(
            start_time=base_window.start_time,
            end_time=base_window.end_time,
            is_closed=True,
            title=override.title,
            note=override.note or "",
        )
    return BookingWindow(
        start_time=override.start_time or base_window.start_time,
        end_time=override.end_time or base_window.end_time,
        title=override.title,
        note=override.note or "",
    )


def _get_room_schedule_slots(*, classroom_id: int, target_date: date) -> list[TimeSlot]:
    schedules = (
        db.session.query(CourseSchedule)
        .filter(
            CourseSchedule.classroom_id == classroom_id,
            CourseSchedule.is_active.is_(True),
            CourseSchedule.weekday == target_date.weekday(),
        )
        .order_by(CourseSchedule.start_time.asc())
        .all()
    )
    return [
        TimeSlot(
            start_at=datetime.combine(target_date, item.start_time),
            end_at=datetime.combine(target_date, item.end_time),
            source="schedule",
            label=item.course_name,
        )
        for item in schedules
    ]


def _get_room_block_slots(
    *,
    classroom_id: int,
    target_date: date,
    day_start: datetime,
    day_end: datetime,
) -> list[TimeSlot]:
    full_day_start = datetime.combine(target_date, time.min)
    full_day_end = datetime.combine(target_date, time.max)
    blocks = (
        db.session.query(ClassroomBlock)
        .filter(
            ClassroomBlock.classroom_id == classroom_id,
            ClassroomBlock.is_active.is_(True),
            ClassroomBlock.start_at < full_day_end,
            ClassroomBlock.end_at > full_day_start,
        )
        .order_by(ClassroomBlock.start_at.asc())
        .all()
    )
    return [
        TimeSlot(
            start_at=max(item.start_at, day_start),
            end_at=min(item.end_at, day_end),
            source="block",
            label=item.title,
        )
        for item in blocks
    ]


def _merge_occupied_slots(slots: list[TimeSlot]) -> list[TimeSlot]:
    merged: list[TimeSlot] = []
    for slot in sorted(slots, key=lambda item: item.start_at):
        if not merged or merged[-1].end_at <= slot.start_at:
            merged.append(slot)
            continue

        previous = merged[-1]
        previous.end_at = max(previous.end_at, slot.end_at)
        if previous.source != slot.source:
            previous.source = "mixed"
        if slot.label:
            previous.label = ", ".join(filter(None, {previous.label, slot.label}))
    return merged


def list_room_availability(*, classroom: Classroom, target_date: date) -> tuple[list[TimeSlot], list[TimeSlot]]:
    booking_window = get_classroom_booking_window(classroom, target_date=target_date)
    day_start = datetime.combine(target_date, booking_window.start_time)
    day_end = datetime.combine(target_date, booking_window.end_time)
    if booking_window.is_closed:
        occupied_slot = TimeSlot(start_at=day_start, end_at=day_end, source="block", label=booking_window.title or booking_window.note or "特定日期停止借用")
        return [occupied_slot], []
    bookings = _get_room_bookings_for_window(
        classroom_id=classroom.id,
        start_at=day_start,
        end_at=day_end,
    )

    booking_slots = [
        TimeSlot(
            start_at=max(booking.start_at, day_start),
            end_at=min(booking.end_at, day_end),
            source="booking",
            label=booking.title,
        )
        for booking in bookings
    ]
    schedule_slots = _get_room_schedule_slots(classroom_id=classroom.id, target_date=target_date)
    block_slots = _get_room_block_slots(
        classroom_id=classroom.id,
        target_date=target_date,
        day_start=day_start,
        day_end=day_end,
    )
    occupied_slots = _merge_occupied_slots(
        [
            slot
            for slot in booking_slots + schedule_slots + block_slots
            if slot.end_at > day_start and slot.start_at < day_end
        ]
    )

    available_slots: list[TimeSlot] = []
    cursor = day_start
    for slot in occupied_slots:
        if cursor < slot.start_at:
            available_slots.append(TimeSlot(start_at=cursor, end_at=slot.start_at))
        if slot.end_at > cursor:
            cursor = slot.end_at

    if cursor < day_end:
        available_slots.append(TimeSlot(start_at=cursor, end_at=day_end))

    return occupied_slots, available_slots


def list_room_grid_cells(*, classroom: Classroom, target_date: date) -> list[RoomGridCell]:
    booking_window = get_classroom_booking_window(classroom, target_date=target_date)
    day_start = datetime.combine(target_date, booking_window.start_time)
    day_end = datetime.combine(target_date, booking_window.end_time)
    slots: list[RoomGridCell] = []

    if booking_window.is_closed:
        for period_code, start_time, end_time in get_booking_periods():
            cursor = datetime.combine(target_date, start_time)
            slot_end = datetime.combine(target_date, end_time)
            status = "block" if cursor >= day_start and slot_end <= day_end else "outside"
            slots.append(RoomGridCell(period_code=period_code, start_at=cursor, end_at=slot_end, status=status, label="停" if status == "block" else "", title=booking_window.title or booking_window.note))
        return slots

    bookings = _get_room_bookings_for_window(
        classroom_id=classroom.id,
        start_at=day_start,
        end_at=day_end,
    )
    schedules = _get_room_schedule_slots(classroom_id=classroom.id, target_date=target_date)
    blocks = _get_room_block_slots(
        classroom_id=classroom.id,
        target_date=target_date,
        day_start=day_start,
        day_end=day_end,
    )

    booking_slots = []
    for booking in bookings:
        booking_slots.append(
            (
                max(booking.start_at, day_start),
                min(booking.end_at, day_end),
                "pending" if booking.status in {"pending", "pending_approval"} else "booked",
                booking.title,
            )
        )

    schedule_slots = [(slot.start_at, slot.end_at, "schedule", slot.label) for slot in schedules]
    block_slots = [(slot.start_at, slot.end_at, "block", slot.label) for slot in blocks]
    occupied_slots = block_slots + schedule_slots + booking_slots

    for period_code, start_time, end_time in get_booking_periods():
        cursor = datetime.combine(target_date, start_time)
        slot_end = datetime.combine(target_date, end_time)
        if cursor < day_start or slot_end > day_end:
            slots.append(
                RoomGridCell(
                    period_code=period_code,
                    start_at=cursor,
                    end_at=slot_end,
                    status="outside",
                )
            )
            continue
        status = "available"
        label = ""
        title = ""
        for occupied_start, occupied_end, occupied_status, occupied_label in occupied_slots:
            if occupied_start < slot_end and occupied_end > cursor:
                status = occupied_status
                label = {
                    "booked": "借",
                    "pending": "申",
                    "schedule": "課",
                    "block": "停",
                }[occupied_status]
                title = occupied_label
                break
        slots.append(
            RoomGridCell(
                period_code=period_code,
                start_at=cursor,
                end_at=slot_end,
                status=status,
                label=label,
                title=title,
            )
        )

    return slots


def has_schedule_conflict(*, classroom_id: int, start_at: datetime, end_at: datetime) -> CourseSchedule | None:
    weekday = start_at.weekday()
    candidate_schedules = (
        db.session.query(CourseSchedule)
        .filter(
            CourseSchedule.classroom_id == classroom_id,
            CourseSchedule.is_active.is_(True),
            CourseSchedule.weekday == weekday,
        )
        .all()
    )
    start_time = start_at.time()
    end_time = end_at.time()
    for item in candidate_schedules:
        if item.start_time < end_time and item.end_time > start_time:
            return item
    return None


def has_block_conflict(*, classroom_id: int, start_at: datetime, end_at: datetime) -> ClassroomBlock | None:
    return (
        db.session.query(ClassroomBlock)
        .filter(
            ClassroomBlock.classroom_id == classroom_id,
            ClassroomBlock.is_active.is_(True),
            ClassroomBlock.start_at < end_at,
            ClassroomBlock.end_at > start_at,
        )
        .order_by(ClassroomBlock.start_at.asc())
        .first()
    )


def get_int_rule(key: str, default: int) -> int:
    row = db.session.query(SystemRule).filter_by(key=key).first()
    if not row:
        return default
    try:
        return int(row.value)
    except ValueError:
        return default


def get_float_rule(key: str, default: float) -> float:
    row = db.session.query(SystemRule).filter_by(key=key).first()
    if not row or row.value == "":
        return default
    try:
        return float(row.value)
    except ValueError:
        return default


def get_optional_time_rule(key: str) -> time | None:
    row = db.session.query(SystemRule).filter_by(key=key).first()
    if not row or not row.value.strip():
        return None
    try:
        return datetime.strptime(row.value.strip(), "%H:%M").time()
    except ValueError:
        return None


def get_csv_rule_values(key: str) -> set[str]:
    row = db.session.query(SystemRule).filter_by(key=key).first()
    if not row or not row.value.strip():
        return set()
    return {value.strip() for value in row.value.split(",") if value.strip()}


def get_optional_int_rule(key: str) -> int | None:
    row = db.session.query(SystemRule).filter_by(key=key).first()
    if not row or not row.value.strip():
        return None
    try:
        return int(row.value.strip())
    except ValueError:
        return None


def room_has_special_hour_limit(classroom: Classroom) -> bool:
    limited_codes = {code.upper() for code in get_csv_rule_values("restricted_classroom_codes")}
    if limited_codes and classroom.code.upper() in limited_codes:
        return True
    limited_types = get_csv_rule_values("restricted_room_types")
    return classroom.room_type in limited_types


def get_booking_duration_limits(classroom: Classroom) -> tuple[int | None, int | None]:
    if not room_has_special_hour_limit(classroom):
        return None, None
    per_booking_limit = get_optional_int_rule("restricted_max_hours_per_booking")
    per_day_limit = get_optional_int_rule("restricted_max_hours_per_day")
    return per_booking_limit, per_day_limit


def department_matches_rule(user_department: str | None, raw_rule_value: str) -> bool:
    department = (user_department or "").strip()
    if not department:
        return False
    keywords = [value.strip() for value in raw_rule_value.split(",") if value.strip()]
    if not keywords:
        return True
    return any(keyword in department for keyword in keywords)


def resolve_auto_approval_risk(*, requester: User, classroom: Classroom, start_at: datetime, end_at: datetime, attendee_count: int) -> str:
    risk_level = "low"
    auto_approve_max_hours = get_int_rule("auto_approve_max_hours", 2)
    if (end_at - start_at).total_seconds() / 3600 > auto_approve_max_hours:
        risk_level = "high"

    max_attendee_ratio = get_float_rule("auto_approve_max_attendee_ratio", 0.8)
    if attendee_count > int(classroom.capacity * max_attendee_ratio):
        risk_level = "high"

    max_attendee_count = db.session.query(SystemRule).filter_by(key="auto_approve_max_attendee_count").first()
    if max_attendee_count and max_attendee_count.value.strip():
        try:
            if attendee_count > int(max_attendee_count.value.strip()):
                risk_level = "high"
        except ValueError:
            pass

    auto_approve_end_time = get_optional_time_rule("auto_approve_end_time")
    if auto_approve_end_time and end_at.time() > auto_approve_end_time:
        risk_level = "high"

    excluded_classrooms = {code.upper() for code in get_csv_rule_values("auto_approve_excluded_classrooms")}
    if classroom.code.upper() in excluded_classrooms:
        risk_level = "high"

    required_department = db.session.query(SystemRule).filter_by(key="auto_approve_required_department").first()
    if required_department and required_department.value.strip():
        if not department_matches_rule(requester.department, required_department.value.strip()):
            risk_level = "high"

    return risk_level


def validate_booking(
    *,
    requester: User,
    classroom: Classroom,
    start_at: datetime,
    end_at: datetime,
    attendee_count: int,
) -> BookingValidationResult:
    if attendee_count > classroom.capacity:
        return BookingValidationResult(False, reason="借用人數超過教室容納上限。")

    if start_at >= end_at:
        return BookingValidationResult(False, reason="借用結束時間需晚於開始時間。")

    booking_window = get_classroom_booking_window(classroom, target_date=start_at.date())
    allowed_start = datetime.combine(start_at.date(), booking_window.start_time)
    allowed_end = datetime.combine(start_at.date(), booking_window.end_time)
    if start_at.date() != end_at.date():
        return BookingValidationResult(False, reason="目前僅開放單日借用。")
    if booking_window.is_closed:
        return BookingValidationResult(False, reason=f"此教室於 {start_at:%Y-%m-%d} 停止借用：{booking_window.title or booking_window.note or '特定日期關閉'}。")
    if start_at < allowed_start or end_at > allowed_end:
        return BookingValidationResult(
            False,
            reason=(
                f"此教室可借用時段為 {booking_window.start_time:%H:%M}-{booking_window.end_time:%H:%M}。"
            ),
        )

    duration_hours = (end_at - start_at).total_seconds() / 3600
    max_hours_per_booking, max_hours_per_day = get_booking_duration_limits(classroom)
    if max_hours_per_booking is not None and duration_hours > max_hours_per_booking:
        return BookingValidationResult(False, reason=f"{classroom.room_type} 單次借用不可超過 {max_hours_per_booking} 小時。")

    day_start = start_at.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = start_at.replace(hour=23, minute=59, second=59, microsecond=999999)
    existing_daily_bookings = (
        db.session.query(BookingRequest)
        .filter(
            BookingRequest.requester_id == requester.id,
            BookingRequest.start_at >= day_start,
            BookingRequest.end_at <= day_end,
            BookingRequest.status.in_(["approved", "pending", "pending_approval"]),
        )
        .all()
    )
    if max_hours_per_day is not None:
        existing_daily_bookings = [item for item in existing_daily_bookings if room_has_special_hour_limit(item.classroom)]
    daily_hours = sum(
        (item.end_at - item.start_at).total_seconds() / 3600.0
        for item in existing_daily_bookings
    )
    if max_hours_per_day is not None and daily_hours + duration_hours > max_hours_per_day:
        return BookingValidationResult(False, reason=f"{classroom.room_type} 每日借用總時數不可超過 {max_hours_per_day} 小時。")

    conflict_exists = bool(
        _get_room_bookings_for_window(
            classroom_id=classroom.id,
            start_at=start_at,
            end_at=end_at,
        )
    )
    if conflict_exists:
        return BookingValidationResult(False, reason="該時段已有借用，請改選其他時間。")

    schedule_conflict = has_schedule_conflict(
        classroom_id=classroom.id,
        start_at=start_at,
        end_at=end_at,
    )
    if schedule_conflict is not None:
        return BookingValidationResult(
            False,
            reason=(
                f"該時段有課程《{schedule_conflict.course_name}》"
                f"（{schedule_conflict.start_time:%H:%M}-{schedule_conflict.end_time:%H:%M}），不可借用。"
            ),
        )

    block_conflict = has_block_conflict(
        classroom_id=classroom.id,
        start_at=start_at,
        end_at=end_at,
    )
    if block_conflict is not None:
        return BookingValidationResult(
            False,
            reason=(
                f"該時段教室停用《{block_conflict.title}》"
                f"（{block_conflict.start_at:%Y-%m-%d %H:%M}-{block_conflict.end_at:%H:%M}），不可借用。"
            ),
        )

    risk_level = resolve_auto_approval_risk(
        requester=requester,
        classroom=classroom,
        start_at=start_at,
        end_at=end_at,
        attendee_count=attendee_count,
    )

    return BookingValidationResult(True, risk_level=risk_level)


def create_booking(
    *,
    requester: User,
    classroom: Classroom,
    title: str,
    purpose: str,
    attendee_count: int,
    start_at: datetime,
    end_at: datetime,
    source: str = "online",
    reason_category: str = "其他",
) -> BookingRequest:
    result = validate_booking(
        requester=requester,
        classroom=classroom,
        start_at=start_at,
        end_at=end_at,
        attendee_count=attendee_count,
    )
    if not result.ok:
        raise ValueError(result.reason)

    status = "approved" if result.risk_level == "low" else "pending_approval"
    booking = BookingRequest(
        requester_id=requester.id,
        classroom_id=classroom.id,
        title=title,
        purpose=purpose,
        reason_category=reason_category,
        attendee_count=attendee_count,
        start_at=start_at,
        end_at=end_at,
        status=status,
        risk_level=result.risk_level,
        source=source,
    )
    db.session.add(booking)
    db.session.flush()

    log_action = "booking_auto_approved" if status == "approved" else "booking_submitted"
    db.session.add(
        AuditLog(
            actor_user_id=requester.id,
            action=log_action,
            entity_type="booking_request",
            entity_id=str(booking.id),
            payload={
                "classroom_id": classroom.id,
                "risk_level": result.risk_level,
                "source": source,
            },
        )
    )
    db.session.commit()
    return booking


def cancel_booking(booking: BookingRequest, actor: User, reason: str) -> None:
    if booking.status in {"cancelled", "rejected"}:
        return

    booking.status = "cancelled"
    booking.cancel_reason = reason
    db.session.add(
        AuditLog(
            actor_user_id=actor.id,
            action="booking_cancelled",
            entity_type="booking_request",
            entity_id=str(booking.id),
            payload={"reason": reason},
        )
    )
    db.session.commit()


def list_visible_bookings_for_role(role_names: set[str], user_id: int):
    query = db.session.query(BookingRequest).order_by(BookingRequest.start_at.desc())
    can_view_all = bool(role_names.intersection({"super_admin", "staff_manager", "workstudy_manager"}))
    if not can_view_all:
        query = query.filter(BookingRequest.requester_id == user_id)
    return query.all()
