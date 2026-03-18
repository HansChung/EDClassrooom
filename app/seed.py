from __future__ import annotations

import click
from flask import Flask

from app.extensions import db
from app.models import Classroom, Role, SystemRule


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
]

DEFAULT_CLASSROOMS = [
    ("L105", "多媒體討論教室", "文館", 65, True, None),
    ("L108", "數位錄音室 B", "文館", 2, True, "每次只能借 2 小時，若無人借用可續借 1 小時，一天以 3 小時為限。"),
    ("L109", "數位錄音室 A", "文館", 2, True, "每次只能借 2 小時，若無人借用可續借 1 小時，一天以 3 小時為限。"),
    ("L111", "影棚", "文館", 10, True, None),
    ("L102", "電腦教室", "文館", 65, False, "請向工頭登記借用"),
    ("L110", "電腦教室", "文館", 70, False, "請向工頭登記借用"),
    ("L103", "蘋果電腦教室", "文館", 32, False, "請向工頭登記借用"),
    ("ED202", "專題製作企劃室", "教育館", 15, True, None),
    ("ED204", "研究生教室", "教育館", 20, True, None),
    ("ED205", "多功能研討室", "教育館", 8, True, None),
]


def init_db_schema() -> None:
    db.create_all()


def seed_default_data() -> None:
    for name, desc in DEFAULT_ROLES:
        if db.session.query(Role).filter_by(name=name).first() is None:
            db.session.add(Role(name=name, description=desc))

    for key, value, desc in DEFAULT_RULES:
        if db.session.query(SystemRule).filter_by(key=key).first() is None:
            db.session.add(SystemRule(key=key, value=value, description=desc))

    for code, name, location, capacity, is_online_bookable, note in DEFAULT_CLASSROOMS:
        if db.session.query(Classroom).filter_by(code=code).first() is None:
            db.session.add(
                Classroom(
                    code=code,
                    name=name,
                    location=location,
                    capacity=capacity,
                    is_online_bookable=is_online_bookable,
                    note=note,
                )
            )
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
