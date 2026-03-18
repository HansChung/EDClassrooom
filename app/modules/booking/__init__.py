from flask import Blueprint

bp = Blueprint("booking", __name__)

from app.modules.booking import routes  # noqa: E402,F401
