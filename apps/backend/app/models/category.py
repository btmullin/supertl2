from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from ..db.base import BaseModel

class Category(BaseModel):
    __tablename__ = 'Category'

    id = Column(Integer, primary_key=True, autoincrement=True)
    parent_id = Column(Integer, ForeignKey('Category.id'), nullable=True)
    name = Column(String, nullable=False)

    # Self-referential relationship
    training_logs = relationship("TrainingLogData", back_populates="category")
    parent = relationship("Category", remote_side=[id], backref="children")
