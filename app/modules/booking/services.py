from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from sqlalchemy import and_

from app.extensions import db
from app.models import (
    AuditLog,
    BookingPeriod,
    BookingRequest,
    Classroom,
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


def get_classroom_booking_window(classroom: Classroom) -> BookingWindow:
    return BookingWindow(
        start_time=classroom.booking_start_time or time(hour=8),
        end_time=classroom.booking_end_time or time(hour=22),
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
    booking_window = get_classroom_booking_window(classroom)
    day_start = datetime.combine(target_date, booking_window.start_time)
    day_end = datetime.combine(target_date, booking_window.end_time)
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
    booking_window = get_classroom_booking_window(classroom)
    day_start = datetime.combine(target_date, booking_window.start_time)
    day_end = datetime.combine(target_date, booking_window.end_time)
    slots: list[RoomGridCell] = []

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

    booking_window = get_classroom_booking_window(classroom)
    allowed_start = datetime.combine(start_at.date(), booking_window.start_time)
    allowed_end = datetime.combine(start_at.date(), booking_window.end_time)
    if start_at.date() != end_at.date():
        return BookingValidationResult(False, reason="目前僅開放單日借用。")
    if start_at < allowed_start or end_at > allowed_end:
        return BookingValidationResult(
            False,
            reason=(
                f"此教室可借用時段為 {booking_window.start_time:%H:%M}-{booking_window.end_time:%H:%M}。"
            ),
        )

    duration_hours = (end_at - start_at).total_seconds() / 3600
    max_hours_per_booking = get_int_rule("max_hours_per_booking", 2)
    if duration_hours > max_hours_per_booking:
        return BookingValidationResult(False, reason=f"單次借用不可超過 {max_hours_per_booking} 小時。")

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
    daily_hours = sum(
        (item.end_at - item.start_at).total_seconds() / 3600.0
        for item in existing_daily_bookings
    )
    max_hours_per_day = get_int_rule("max_hours_per_day", 3)
    if daily_hours + duration_hours > max_hours_per_day:
        return BookingValidationResult(False, reason=f"每日借用總時數不可超過 {max_hours_per_day} 小時。")

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

    risk_level = "low"
    auto_approve_max_hours = get_int_rule("auto_approve_max_hours", 2)
    if duration_hours > auto_approve_max_hours:
        risk_level = "high"
    if attendee_count > int(classroom.capacity * 0.8):
        risk_level = "high"

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
