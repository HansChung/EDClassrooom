from __future__ import annotations

import click
from datetime import time
from flask import Flask
from sqlalchemy import text

from app.extensions import db
from app.models import BookingPeriod, Classroom, Role, SystemRule


DEFAULT_ROLES = [
    ("user", "一般使用者"),
    ("workstudy_manager", "工讀生管理者"),
    ("staff_manager", "承辦人員管理者"),
    ("super_admin", "最高管理者"),
]

DEFAULT_RULES = [
    ("max_hours_per_booking", "2", "單次借用上限（小時）"),
    ("max_hours_per_day", "3", "每日借用總時數上限（小時）"),
    ("auto_approve_max_hours", "2", "自動核准時數上限（小時）"),
    ("auto_approve_max_attendee_ratio", "0.8", "超過教室容量比例時改為人工審核（0-1）"),
    ("auto_approve_max_attendee_count", "", "超過此人數改為人工審核，空白代表不限制"),
    ("auto_approve_end_time", "", "晚於此時間結束時改為人工審核，格式 HH:MM，空白代表不限制"),
    ("auto_approve_excluded_classrooms", "", "不可自動核准的教室代碼，以逗號分隔"),
    ("auto_approve_required_department", "", "限定特定系所才能自動核准，空白代表不限制"),
]

DEFAULT_BOOKING_PERIODS = [
    ("01", time(hour=8, minute=10), time(hour=9, minute=0), 1),
    ("02", time(hour=9, minute=10), time(hour=10, minute=0), 2),
    ("03", time(hour=10, minute=10), time(hour=11, minute=0), 3),
    ("04", time(hour=11, minute=10), time(hour=12, minute=0), 4),
    ("05", time(hour=12, minute=10), time(hour=13, minute=0), 5),
    ("06", time(hour=13, minute=10), time(hour=14, minute=0), 6),
    ("07", time(hour=14, minute=10), time(hour=15, minute=0), 7),
    ("08", time(hour=15, minute=10), time(hour=16, minute=0), 8),
    ("09", time(hour=16, minute=10), time(hour=17, minute=0), 9),
    ("10", time(hour=17, minute=10), time(hour=18, minute=0), 10),
    ("11", time(hour=18, minute=20), time(hour=19, minute=10), 11),
    ("12", time(hour=19, minute=20), time(hour=20, minute=10), 12),
    ("13", time(hour=20, minute=20), time(hour=21, minute=10), 13),
    ("14", time(hour=21, minute=20), time(hour=22, minute=10), 14),
]

DEFAULT_CLASSROOMS = [
    ("L105", "多媒體討論教室", "文學館", "教室", 65, True, None, time(hour=9), time(hour=18)),
    ("L108", "數位錄音室 B", "文學館", "錄音室", 2, True, "每次只能借 2 小時，若無人借用可續借 1 小時，一天以 3 小時為限。", time(hour=9), time(hour=18)),
    ("L109", "數位錄音室 A", "文學館", "錄音室", 2, True, "每次只能借 2 小時，若無人借用可續借 1 小時，一天以 3 小時為限。", time(hour=9), time(hour=18)),
    ("L111", "影棚", "文學館", "影棚", 10, True, None, time(hour=9), time(hour=18)),
    ("L102", "電腦教室", "文學館", "電腦教室", 65, False, "請向工頭登記借用", time(hour=9), time(hour=18)),
    ("L110", "電腦教室", "文學館", "電腦教室", 70, False, "請向工頭登記借用", time(hour=9), time(hour=18)),
    ("L103", "蘋果電腦教室", "文學館", "電腦教室", 32, False, "請向工頭登記借用", time(hour=9), time(hour=18)),
    ("ED202", "專題製作企劃室", "教育館", "教室", 15, True, None, time(hour=8), time(hour=17)),
    ("ED204", "研究生教室", "教育館", "教室", 20, True, None, time(hour=8), time(hour=17)),
    ("ED205", "多功能研討室", "教育館", "會議室", 8, True, None, time(hour=8), time(hour=17)),
]


def init_db_schema() -> None:
    db.create_all()
    _ensure_schema_columns()


def _ensure_schema_columns() -> None:
    inspector = db.inspect(db.engine)

    if "classrooms" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("classrooms")}
        statements: list[str] = []
        if "booking_start_time" not in columns:
            statements.append("ALTER TABLE classrooms ADD COLUMN booking_start_time TIME NOT NULL DEFAULT '08:00:00'")
        if "booking_end_time" not in columns:
            statements.append("ALTER TABLE classrooms ADD COLUMN booking_end_time TIME NOT NULL DEFAULT '22:00:00'")
        if "room_type" not in columns:
            statements.append("ALTER TABLE classrooms ADD COLUMN room_type VARCHAR(40) NOT NULL DEFAULT '教室'")
        for statement in statements:
            db.session.execute(text(statement))

    if "users" in inspector.get_table_names():
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        if "department" not in user_columns:
            db.session.execute(text("ALTER TABLE users ADD COLUMN department VARCHAR(120)"))

    db.session.commit()


def seed_default_data() -> None:
    for name, desc in DEFAULT_ROLES:
        if db.session.query(Role).filter_by(name=name).first() is None:
            db.session.add(Role(name=name, description=desc))

    for key, value, desc in DEFAULT_RULES:
        if db.session.query(SystemRule).filter_by(key=key).first() is None:
            db.session.add(SystemRule(key=key, value=value, description=desc))

    for code, start_time, end_time, sort_order in DEFAULT_BOOKING_PERIODS:
        if db.session.query(BookingPeriod).filter_by(code=code).first() is None:
            db.session.add(
                BookingPeriod(
                    code=code,
                    start_time=start_time,
                    end_time=end_time,
                    sort_order=sort_order,
                    is_active=True,
                )
            )

    old_default_start = time(hour=8)
    old_default_end = time(hour=22)

    for code, name, location, room_type, capacity, is_online_bookable, note, booking_start_time, booking_end_time in DEFAULT_CLASSROOMS:
        room = db.session.query(Classroom).filter_by(code=code).first()
        if room is None:
            db.session.add(
                Classroom(
                    code=code,
                    name=name,
                    location=location,
                    room_type=room_type,
                    capacity=capacity,
                    is_online_bookable=is_online_bookable,
                    booking_start_time=booking_start_time,
                    booking_end_time=booking_end_time,
                    note=note,
                )
            )
            continue

        if room.booking_start_time == old_default_start and room.booking_end_time == old_default_end:
            room.booking_start_time = booking_start_time
            room.booking_end_time = booking_end_time
        if not room.room_type or room.room_type == "教室":
            room.room_type = room_type
        if room.location == "文館":
            room.location = "文學館"
    db.session.commit()


def register_seed_commands(app: Flask) -> None:
    @app.cli.command("init-db")
    def init_db():
        init_db_schema()
        click.echo("資料表建立完成。")

    @app.cli.command("seed-defaults")
    def seed_defaults():
        seed_default_data()
        click.echo("預設角色、規則與教室已匯入。")
