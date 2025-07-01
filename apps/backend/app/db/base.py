from flask_sqlalchemy import SQLAlchemy

sqla_db = SQLAlchemy()

class BaseModel(sqla_db.Model):
    __abstract__ = True
