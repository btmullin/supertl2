from sqlalchemy import Column, Integer, String, DateTime, JSON
from sqlalchemy.orm import relationship

from ..db.base import BaseModel

class StravaActivity(BaseModel):
    __tablename__ = "StravaActivity"

    activityId = Column(Integer, primary_key=True)
    name = Column(String)
    startDateTime = Column(DateTime)
    sportType = Column(String)
    distance = Column(Integer)
    movingTimeInSeconds = Column(Integer)
    description = Column(String)
    elevation = Column(Integer)
    data = Column(JSON)

    training_log = relationship("TrainingLogData", back_populates="strava_activity", uselist=False)

    streams = relationship("StravaActivityStream", back_populates="strava_activity", cascade="all, delete-orphan")
