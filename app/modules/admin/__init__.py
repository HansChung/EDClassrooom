from flask import Blueprint

bp = Blueprint("admin", __name__)

from app.modules.admin import routes  # noqa: E402,F401
