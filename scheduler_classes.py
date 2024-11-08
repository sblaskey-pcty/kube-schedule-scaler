from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import time

class ScheduleType(Enum):
    Everday = "everyday"
    Weekday = 'weekday'

class ScheduleFrequency(Enum):
    Custom = "custom"
    Hourly = "hourly"

@dataclass
class Duration:
    hours: Optional[int] = None
    minutes: Optional[int] = None

@dataclass
class Schedule:
    start: time
    duration: Duration
    target_minReplicas: int
    default_minReplicas: int
    scale_duration: Optional[Duration] = None


@dataclass
class ScheduleConfig:
    custom: Dict[str, Schedule] = field(default_factory=dict)
    hourly: Dict[str, Schedule] = field(default_factory=dict)