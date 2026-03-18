from __future__ import annotations

from urllib.parse import urlparse, urljoin

from flask import current_app, flash, redirect, request, session, url_for
from flask_login import current_user, login_user, logout_user

from app.extensions import db, oauth
from app.models import Role, User
from app.modules.auth import bp


def _is_safe_redirect_url(target: str) -> bool:
    host_url = urlparse(request.host_url)
    redirect_url = urlparse(urljoin(request.host_url, target))
    return redirect_url.scheme in ("http", "https") and host_url.netloc == redirect_url.netloc


def _resolve_roles_by_upn(upn: str) -> list[Role]:
    normalized = upn.lower()
    role_names = {"user"}
    if normalized in current_app.config["WORKSTUDY_UPNS"]:
        role_names.add("workstudy_manager")
    if normalized in current_app.config["STAFF_UPNS"]:
        role_names.add("staff_manager")
    if normalized in current_app.config["ADMIN_UPNS"]:
        role_names.add("super_admin")
    return list(db.session.query(Role).filter(Role.name.in_(role_names)).all())


@bp.route("/login")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    redirect_uri = current_app.config["OIDC_REDIRECT_URI"]
    return oauth.microsoft.authorize_redirect(redirect_uri)


@bp.route("/callback")
def callback():
    token = oauth.microsoft.authorize_access_token()
    userinfo = token.get("userinfo")
    if not userinfo:
        userinfo = oauth.microsoft.parse_id_token(token)

    tenant_id = userinfo.get("tid")
    allowed_tenant_ids = current_app.config["OIDC_ALLOWED_TENANT_IDS"]
    if allowed_tenant_ids and tenant_id not in allowed_tenant_ids:
        flash("僅允許本校 Office 365 帳號登入。", "danger")
        return redirect(url_for("main.index"))

    oid = userinfo.get("oid") or userinfo.get("sub")
    upn = (userinfo.get("preferred_username") or userinfo.get("email") or "").lower()
    display_name = userinfo.get("name") or upn

    if not oid or not upn:
        flash("無法取得 Office 365 使用者資訊。", "danger")
        return redirect(url_for("main.index"))

    user = db.session.query(User).filter_by(oid=oid).first()
    if user is None:
        user = User(
            oid=oid,
            upn=upn,
            display_name=display_name,
            email=userinfo.get("email"),
            is_active_user=True,
        )
        db.session.add(user)
    else:
        user.upn = upn
        user.display_name = display_name
        user.email = userinfo.get("email")

    user.roles = _resolve_roles_by_upn(upn)
    db.session.commit()

    login_user(user, remember=True)
    flash(f"登入成功，歡迎 {user.display_name}。", "success")

    next_url = session.pop("next_url", None) or request.args.get("next")
    if next_url and _is_safe_redirect_url(next_url):
        return redirect(next_url)
    return redirect(url_for("main.index"))


@bp.route("/logout")
def logout():
    logout_user()
    flash("已登出。", "info")
    return redirect(url_for("main.index"))
