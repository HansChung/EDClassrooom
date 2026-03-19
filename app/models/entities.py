from __future__ import annotations

from datetime import datetime, time
from typing import Any

from flask_login import UserMixin
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


class UserRole(db.Model):
    __tablename__ = "user_roles"

    user_id: Mapped[int] = mapped_column(db.ForeignKey("users.id"), primary_key=True)
    role_id: Mapped[int] = mapped_column(db.ForeignKey("roles.id"), primary_key=True)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    oid: Mapped[str] = mapped_column(db.String(64), unique=True, nullable=False, index=True)
    upn: Mapped[str] = mapped_column(db.String(255), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(db.String(120), nullable=False)
    email: Mapped[str] = mapped_column(db.String(255), nullable=True)
    is_active_user: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    roles: Mapped[list["Role"]] = relationship(
        secondary="user_roles",
        back_populates="users",
        lazy="selectin",
    )
    bookings: Mapped[list["BookingRequest"]] = relationship(back_populates="requester")

    @property
    def is_active(self) -> bool:
        return self.is_active_user

    def has_role(self, role_name: str) -> bool:
        return any(role.name == role_name for role in self.roles)

    def has_any_role(self, role_names: set[str]) -> bool:
        return any(role.name in role_names for role in self.roles)


class Role(db.Model):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(db.String(50), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(db.String(255), nullable=False)

    users: Mapped[list[User]] = relationship(
        secondary="user_roles",
        back_populates="roles",
        lazy="selectin",
    )


class Classroom(db.Model):
    __tablename__ = "classrooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(db.String(20), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(db.String(120), nullable=False)
    location: Mapped[str] = mapped_column(db.String(80), nullable=False)
    capacity: Mapped[int] = mapped_column(nullable=False)
    is_online_bookable: Mapped[bool] = mapped_column(default=True, nullable=False)
    booking_start_time: Mapped[time] = mapped_column(nullable=False, default=time(hour=8))
    booking_end_time: Mapped[time] = mapped_column(nullable=False, default=time(hour=22))
    note: Mapped[str | None] = mapped_column(db.String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    bookings: Mapped[list["BookingRequest"]] = relationship(back_populates="classroom")
    schedules: Mapped[list["CourseSchedule"]] = relationship(back_populates="classroom")
    blocks: Mapped[list["ClassroomBlock"]] = relationship(back_populates="classroom")


class CourseSchedule(db.Model):
    __tablename__ = "course_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    classroom_id: Mapped[int] = mapped_column(
        db.ForeignKey("classrooms.id"), nullable=False, index=True
    )
    course_name: Mapped[str] = mapped_column(db.String(255), nullable=False)
    instructor_name: Mapped[str | None] = mapped_column(db.String(120), nullable=True)
    weekday: Mapped[int] = mapped_column(nullable=False, index=True)
    start_time: Mapped[time] = mapped_column(nullable=False)
    end_time: Mapped[time] = mapped_column(nullable=False)
    semester_label: Mapped[str] = mapped_column(db.String(80), nullable=False, default="current")
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    classroom: Mapped[Classroom] = relationship(back_populates="schedules")


class ClassroomBlock(db.Model):
    __tablename__ = "classroom_blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    classroom_id: Mapped[int] = mapped_column(
        db.ForeignKey("classrooms.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(db.String(255), nullable=False)
    reason: Mapped[str | None] = mapped_column(db.String(500), nullable=True)
    block_type: Mapped[str] = mapped_column(db.String(30), nullable=False, default="maintenance")
    start_at: Mapped[datetime] = mapped_column(nullable=False, index=True)
    end_at: Mapped[datetime] = mapped_column(nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    classroom: Mapped[Classroom] = relationship(back_populates="blocks")


class BookingRequest(db.Model):
    __tablename__ = "booking_requests"
    __table_args__ = (
        UniqueConstraint("classroom_id", "start_at", "end_at", name="uq_room_timeslot"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    requester_id: Mapped[int] = mapped_column(db.ForeignKey("users.id"), nullable=False, index=True)
    classroom_id: Mapped[int] = mapped_column(
        db.ForeignKey("classrooms.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(db.String(255), nullable=False)
    purpose: Mapped[str] = mapped_column(db.String(500), nullable=False)
    attendee_count: Mapped[int] = mapped_column(nullable=False)
    start_at: Mapped[datetime] = mapped_column(nullable=False, index=True)
    end_at: Mapped[datetime] = mapped_column(nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        db.String(30), nullable=False, default="pending", index=True
    )
    risk_level: Mapped[str] = mapped_column(db.String(20), nullable=False, default="low")
    cancel_reason: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    source: Mapped[str] = mapped_column(
        db.String(20), nullable=False, default="online"
    )  # online/manual
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    requester: Mapped[User] = relationship(back_populates="bookings")
    classroom: Mapped[Classroom] = relationship(back_populates="bookings")
    approvals: Mapped[list["BookingApproval"]] = relationship(back_populates="booking")


class BookingApproval(db.Model):
    __tablename__ = "booking_approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        db.ForeignKey("booking_requests.id"), nullable=False, index=True
    )
    approver_id: Mapped[int] = mapped_column(db.ForeignKey("users.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(db.String(20), nullable=False)  # approved/rejected
    comment: Mapped[str | None] = mapped_column(db.String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False)

    booking: Mapped[BookingRequest] = relationship(back_populates="approvals")


class SystemRule(db.Model):
    __tablename__ = "system_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(db.String(100), unique=True, nullable=False, index=True)
    value: Mapped[str] = mapped_column(db.String(255), nullable=False)
    description: Mapped[str] = mapped_column(db.String(255), nullable=False)

    @staticmethod
    def as_map() -> dict[str, str]:
        rows = db.session.query(SystemRule).all()
        return {row.key: row.value for row in rows}


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(db.ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(db.String(120), nullable=False)
    entity_type: Mapped[str] = mapped_column(db.String(80), nullable=False)
    entity_id: Mapped[str] = mapped_column(db.String(80), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(db.JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False, index=True)


class Notification(db.Model):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(db.ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(db.String(255), nullable=False)
    body: Mapped[str] = mapped_column(db.String(500), nullable=False)
    link: Mapped[str | None] = mapped_column(db.String(255), nullable=True)
    is_read: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, nullable=False, index=True)
