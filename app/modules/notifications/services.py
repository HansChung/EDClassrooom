from app.extensions import db
from app.models import Notification, User


def create_notification(*, user_id: int, title: str, body: str, link: str | None = None) -> None:
    db.session.add(
        Notification(
            user_id=user_id,
            title=title,
            body=body,
            link=link,
        )
    )


def create_notifications_for_roles(*, role_names: set[str], title: str, body: str, link: str | None = None) -> None:
    users = db.session.query(User).all()
    for user in users:
        if any(role.name in role_names for role in user.roles):
            create_notification(user_id=user.id, title=title, body=body, link=link)
