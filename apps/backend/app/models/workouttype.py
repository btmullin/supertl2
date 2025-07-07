from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.orm import relationship
from ..db.base import BaseModel

class WorkoutType(BaseModel):
    __tablename__ = 'WorkoutType'

    id = Column(Integer, primary_key=True)
    name = Column(String)
    description = Column(Text, nullable=True)

    training_logs = relationship("TrainingLogData", back_populates="workout_type")
