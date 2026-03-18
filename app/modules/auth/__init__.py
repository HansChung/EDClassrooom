from flask import Blueprint

bp = Blueprint("auth", __name__)

from app.modules.auth import routes  # noqa: E402,F401
