from flask import Blueprint

bp = Blueprint("notifications", __name__)

from app.modules.notifications import routes  # noqa: E402,F401
