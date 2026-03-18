from authlib.integrations.flask_client import OAuth
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
oauth = OAuth()

login_manager.login_view = "auth.login"
login_manager.login_message = "請先使用 Office 365 登入。"
