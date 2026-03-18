import os
from datetime import timedelta


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///classroom_booking.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    OIDC_TENANT_ID = os.getenv("OIDC_TENANT_ID", "common")
    OIDC_CLIENT_ID = os.getenv("OIDC_CLIENT_ID", "")
    OIDC_CLIENT_SECRET = os.getenv("OIDC_CLIENT_SECRET", "")
    OIDC_REDIRECT_URI = os.getenv("OIDC_REDIRECT_URI", "http://localhost:5000/auth/callback")
    OIDC_METADATA_URL = (
        f"https://login.microsoftonline.com/{OIDC_TENANT_ID}/v2.0/.well-known/openid-configuration"
    )
    OIDC_ALLOWED_TENANT_IDS = {
        value.strip()
        for value in os.getenv("OIDC_ALLOWED_TENANT_IDS", "").split(",")
        if value.strip()
    }

    ADMIN_UPNS = {
        value.strip().lower()
        for value in os.getenv("ADMIN_UPNS", "").split(",")
        if value.strip()
    }
    STAFF_UPNS = {
        value.strip().lower()
        for value in os.getenv("STAFF_UPNS", "").split(",")
        if value.strip()
    }
    WORKSTUDY_UPNS = {
        value.strip().lower()
        for value in os.getenv("WORKSTUDY_UPNS", "").split(",")
        if value.strip()
    }

    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
    REMEMBER_COOKIE_DURATION = timedelta(days=7)
