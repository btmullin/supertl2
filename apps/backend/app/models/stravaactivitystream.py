from sqlalchemy import Column, ForeignKey, String, DateTime, JSON, PrimaryKeyConstraint
from sqlalchemy.orm import relationship

from ..db.base import BaseModel

class StravaActivityStream(BaseModel):
    __tablename__ = 'StravaActivityStream'

    activityId = Column(String(255), ForeignKey("StravaActivity.activityId"), nullable=False)
    streamType = Column(String(255), nullable=False)
    createdOn = Column(DateTime, nullable=False)
    data = Column(JSON, nullable=False)  # JSON stored as CLOB
    bestAverages = Column(JSON, nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint('activityId', 'streamType'),
    )

    strava_activity = relationship("StravaActivity", back_populates="streams")
