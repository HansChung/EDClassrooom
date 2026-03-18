from __future__ import annotations

from functools import wraps

from flask import abort
from flask_login import current_user


def roles_required(*role_names: str):
    required = set(role_names)

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return abort(401)
            if not current_user.has_any_role(required):
                return abort(403)
            return func(*args, **kwargs)

        return wrapper

    return decorator
