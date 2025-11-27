from sqlalchemy import Column, Integer, String, Float
from sqlalchemy.orm import relationship

from ..db.base import BaseModel


class Activity(BaseModel):
    __tablename__ = "activity"

    id = Column(Integer, primary_key=True)

    # Canonical timestamps stored as ISO8601 strings (matching your schema)
    start_time_utc = Column(String, nullable=False)
    end_time_utc = Column(String, nullable=True)

    elapsed_time_s = Column(Integer, nullable=True)
    moving_time_s = Column(Integer, nullable=True)
    distance_m = Column(Float, nullable=True)

    name = Column(String, nullable=True)
    sport = Column(String, nullable=True)
    source_quality = Column(Integer, default=0)

    created_at_utc = Column(String, nullable=False)
    updated_at_utc = Column(String, nullable=False)

    # Link to TrainingLogData (canonical_activity_id)
    training_logs = relationship(
        "TrainingLogData",
        back_populates="canonical_activity",
    )

    # Optional: later you can add an ActivitySource model and uncomment this:
    #
    # sources = relationship(
    #     "ActivitySource",
    #     back_populates="activity",
    # )
