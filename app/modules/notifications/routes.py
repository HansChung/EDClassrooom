from flask import redirect, render_template, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Notification
from app.modules.notifications import bp


@bp.route("/")
@login_required
def list_notifications():
    notifications = (
        db.session.query(Notification)
        .filter(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
        .all()
    )
    return render_template("notifications/list.html", notifications=notifications)


@bp.route("/<int:notification_id>/read", methods=["POST"])
@login_required
def mark_read(notification_id: int):
    notification = db.session.get(Notification, notification_id)
    if notification is None or notification.user_id != current_user.id:
        return redirect(url_for("notifications.list_notifications"))

    notification.is_read = True
    db.session.commit()
    return redirect(notification.link or url_for("notifications.list_notifications"))
