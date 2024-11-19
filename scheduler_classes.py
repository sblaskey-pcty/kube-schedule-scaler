from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import time

Days = [
    'everyday',
    'weekday'
    'weekend',
    'monday',
    'tuesday',
    'wednesday',
    'thursday',
    'friday',
    'saturday',
    'sunday'
]

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
    name: str
    start: time
    total_duration: Duration
    target_minReplicas: int
    default_minReplicas: int
    scale_duration: Optional[Duration] = None
    days: List[str] = field(default_factory=list)

    def __post__init__(self):
        self.validate_days()

    def validate_days(self):
        for day in self.days:
            if day.lower() not in Days:
                raise ValueError(f"Invalidate day: {day}")

@dataclass
class ScheduleConfig:
    custom: Dict[str, Schedule] = field(default_factory=dict)
    hourly: Dict[str, Schedule] = field(default_factory=dict)

    def merge(self, other: 'ScheduleConfig') -> 'ScheduleConfig':
        merged_custom = {**self.custom, **other.custom}
        merged_hourly = {**self.hourly, **other.hourly}
        return ScheduleConfig(custom=merged_custom, hourly=merged_hourly)
    
    def remove(self, other: 'ScheduleConfig') -> 'ScheduleConfig':
        for key in other.custom:
            if key in self.custom:
                del self.custom[key]
        for key in other.hourly:
            if key in self.hourly:
                del self.hourly[key]
        return self

@dataclass
class updateMinReplicasRequest:
    update_required: bool
    target_minReplicas: int