from flask import render_template
from flask_login import current_user

from app.extensions import db
from app.models import BookingRequest, Classroom
from app.modules.main import bp


@bp.route("/")
def index():
    online_rooms = db.session.query(Classroom).filter_by(is_online_bookable=True, is_active=True).all()
    latest_bookings = []
    if current_user.is_authenticated:
        latest_bookings = (
            db.session.query(BookingRequest)
            .filter_by(requester_id=current_user.id)
            .order_by(BookingRequest.start_at.desc())
            .limit(5)
            .all()
        )
    return render_template(
        "index.html",
        online_rooms=online_rooms,
        latest_bookings=latest_bookings,
    )
