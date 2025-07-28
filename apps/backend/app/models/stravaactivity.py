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
    averageHeartRate = Column(Integer)
    maxHeartRate = Column(Integer)
    calories = Column(Integer)
    averagePower = Column(Integer)

    training_log = relationship("TrainingLogData", back_populates="strava_activity", uselist=False)

    streams = relationship("StravaActivityStream", back_populates="strava_activity", cascade="all, delete-orphan")

    def getHRPlotData(self):
        """Get the heart rate stream data."""
        hr = None
        time = None
        for stream in self.streams:
            if stream.streamType == "heartrate":
                hr = stream.data
            if stream.streamType == "time":
                time = stream.data
        if hr and time:
            return [{"x": t, "y": y} for t, y in zip(time, hr)]
        return None
    
    def getAltitudePlotData(self):
        """Get the altitude stream data."""
        altitude = None
        time = None
        for stream in self.streams:
            if stream.streamType == "altitude":
                altitude = stream.data
            if stream.streamType == "time":
                time = stream.data
        if altitude and time:
            return [{"x": t, "y": a} for t, a in zip(time, altitude)]
        return None
