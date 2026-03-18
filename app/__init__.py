from flask import Flask

from app.config import Config
from app.extensions import db, login_manager, migrate, oauth
from app.models import User


def create_app(config_class: type[Config] = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)

    register_extensions(app)
    register_blueprints(app)
    register_cli(app)

    return app


def register_extensions(app: Flask) -> None:
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    oauth.init_app(app)

    oauth.register(
        name="microsoft",
        server_metadata_url=app.config["OIDC_METADATA_URL"],
        client_id=app.config["OIDC_CLIENT_ID"],
        client_secret=app.config["OIDC_CLIENT_SECRET"],
        client_kwargs={"scope": "openid profile email User.Read"},
    )


def register_blueprints(app: Flask) -> None:
    from app.modules.main import bp as main_bp
    from app.modules.auth import bp as auth_bp
    from app.modules.booking import bp as booking_bp
    from app.modules.approval import bp as approval_bp
    from app.modules.admin import bp as admin_bp
    from app.modules.calendar import bp as calendar_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(booking_bp, url_prefix="/bookings")
    app.register_blueprint(approval_bp, url_prefix="/approvals")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(calendar_bp, url_prefix="/calendar")


def register_cli(app: Flask) -> None:
    from app.seed import register_seed_commands

    register_seed_commands(app)


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    return db.session.get(User, int(user_id))
