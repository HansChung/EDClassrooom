from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from sqlalchemy import and_, func

from app.extensions import db
from app.models import AuditLog, BookingRequest, Classroom, SystemRule, User


@dataclass
class BookingValidationResult:
    ok: bool
    risk_level: str = "low"
    reason: str = ""


@dataclass
class TimeSlot:
    start_at: datetime
    end_at: datetime


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


def list_room_availability(*, classroom_id: int, target_date: date) -> tuple[list[TimeSlot], list[TimeSlot]]:
    day_start = datetime.combine(target_date, time(hour=8))
    day_end = datetime.combine(target_date, time(hour=22))
    bookings = _get_room_bookings_for_window(
        classroom_id=classroom_id,
        start_at=day_start,
        end_at=day_end,
    )

    occupied_slots = [
        TimeSlot(
            start_at=max(booking.start_at, day_start),
            end_at=min(booking.end_at, day_end),
        )
        for booking in bookings
    ]

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

    duration_hours = (end_at - start_at).total_seconds() / 3600
    max_hours_per_booking = get_int_rule("max_hours_per_booking", 2)
    if duration_hours > max_hours_per_booking:
        return BookingValidationResult(False, reason=f"單次借用不可超過 {max_hours_per_booking} 小時。")

    day_start = start_at.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = start_at.replace(hour=23, minute=59, second=59, microsecond=999999)
    daily_hours = (
        db.session.query(
            func.coalesce(
                func.sum(
                    (func.extract("epoch", BookingRequest.end_at - BookingRequest.start_at) / 3600.0)
                ),
                0.0,
            )
        )
        .filter(
            BookingRequest.requester_id == requester.id,
            BookingRequest.start_at >= day_start,
            BookingRequest.end_at <= day_end,
            BookingRequest.status.in_(["approved", "pending"]),
        )
        .scalar()
        or 0.0
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
