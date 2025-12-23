from datetime import date, datetime
from sqlalchemy import Column, Integer, String, Date, DateTime, Boolean
from ..db.base import BaseModel

class Season(BaseModel):
    __tablename__ = "Season"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Season {self.id} {self.name} {self.start_date}..{self.end_date}>"

    @property
    def label(self) -> str:
        # Nice for dropdowns
        return f"{self.name} ({self.start_date:%b %d, %Y} - {self.end_date:%b %d, %Y})"
