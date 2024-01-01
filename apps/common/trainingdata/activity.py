from dataclasses import dataclass
from typing import Optional

@dataclass
class Activity:
    title: Optional[str] = "Untitled"
    description: Optional[str] = ""
    duration_sec: Optional[int] = 0
    distance_m: Optional[float] = 0.0
    type_key: Optional[int] = 0
    elevation_m: Optional[float] = 0.0