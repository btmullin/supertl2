from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from ..db.base import BaseModel


class ActivitySource(BaseModel):
    __tablename__ = "activity_source"

    id = Column(Integer, primary_key=True)

    # FK to canonical activity
    activity_id = Column(
        Integer,
        ForeignKey("activity.id", ondelete="CASCADE"),
        nullable=False,
    )

    # 'strava' or 'sporttracks' (DB has CHECK constraint)
    source = Column(String, nullable=False)

    # Strava.activityId or SportTracks guid/row
    source_activity_id = Column(String, nullable=False)

    # Denormalized source info (may or may not be populated)
    start_time_utc = Column(String, nullable=True)
    elapsed_time_s = Column(Integer, nullable=True)
    distance_m = Column(Float, nullable=True)
    sport = Column(String, nullable=True)
    payload_hash = Column(String, nullable=True)
    ingested_at_utc = Column(String, nullable=False)
    match_confidence = Column(String, nullable=True)
    start_time_local = Column(String, nullable=True)

    # ORM relationship back to Activity
    activity = relationship(
        "Activity",
        back_populates="sources",
    )

    __table_args__ = (
        # matches the DB UNIQUE (source, source_activity_id)
        UniqueConstraint(
            "source",
            "source_activity_id",
            name="uq_activity_source_source_key",
        ),
    )
