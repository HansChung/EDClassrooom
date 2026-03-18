from flask import Blueprint

bp = Blueprint("approval", __name__)

from app.modules.approval import routes  # noqa: E402,F401
