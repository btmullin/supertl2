from sqlalchemy import Column, Integer, String, Float, Text, text
from ..db.base import BaseModel

class DailyHealth(BaseModel):
    __tablename__ = "daily_health"

    id = Column(Integer, primary_key=True)

    # YYYY-MM-DD string (viewer/home local)
    date_local = Column(String, nullable=False, unique=True, index=True)

    weight_kg = Column(Float, nullable=True)
    body_fat_pct = Column(Float, nullable=True)
    resting_hr_bpm = Column(Float, nullable=True)
    hrv_ms = Column(Float, nullable=True)

    food_quality_score = Column(Integer, nullable=True)

    notes = Column(Text, nullable=True)

    created_at_utc = Column(
        String,
        nullable=False,
        server_default=text("(strftime('%Y-%m-%dT%H:%M:%SZ','now'))"),
    )
    updated_at_utc = Column(
        String,
        nullable=False,
        server_default=text("(strftime('%Y-%m-%dT%H:%M:%SZ','now'))"),
    )