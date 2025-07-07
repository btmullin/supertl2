from sqlalchemy import Column, Integer, String, Text, ForeignKey
from sqlalchemy.orm import relationship

from ..db.base import BaseModel

class TrainingLogData(BaseModel):
    __tablename__ = 'TrainingLogData'

    activityId = Column(String, ForeignKey('StravaActivity.activityId'), primary_key=True)
    workoutTypeId = Column(Integer, ForeignKey('WorkoutType.id'), nullable=True)
    categoryId = Column(Integer, ForeignKey('Category.id'), nullable=True)
    notes = Column(Text, nullable=True)
    tags = Column(Text, nullable=True)
    isTraining = Column(Integer, default=2)

    # Relationships
    strava_activity = relationship("StravaActivity", back_populates="training_log", uselist=False)
    workout_type = relationship("WorkoutType", back_populates="training_logs")
    category = relationship("Category", back_populates="training_logs")
