from sqlalchemy import Column, String, Integer, Float, Text, CheckConstraint
from sqlalchemy.orm import relationship

from ..db.base import BaseModel

class SportTracksActivity(BaseModel):
    __tablename__ = "sporttracks_activity"

    # TEXT PRIMARY KEY
    activity_id = Column(String, primary_key=True)

    # Local start date & time (TEXT)
    start_date = Column(String)      # 'YYYY-MM-DD'
    start_time = Column(String)      # 'HH:MM:SS'

    # Metrics
    distance_m = Column(Float)       # meters
    duration_s = Column(Float)       # seconds
    avg_pace_s_per_km = Column(Float)   # sec/km
    elev_gain_m = Column(Float)      # meters
    avg_heartrate_bpm = Column(Float)   # bpm
    avg_power_w = Column(Float)         # watts
    calories_kcal = Column(Float)       # kcal

    # Metadata
    category = Column(String)        # SportTracks category text
    notes = Column(Text)             # free text

    # 0/1 field with CHECK constraint
    has_tcx = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint("has_tcx IN (0,1)", name="ck_st_has_tcx_bool"),
    )

    sources = relationship(
        "ActivitySource",
        primaryjoin="SportTracksActivity.activity_id == foreign(ActivitySource.source_activity_id)",
        viewonly=True,
    )
