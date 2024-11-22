from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import time

Scale_Type = [
    'custom',
    'hourly'
]

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
    Everday = 'everyday'
    Weekday = 'weekday'
    Weekend = 'weekend'
    Monday = 'monday'
    Tuesday = 'tuesday'
    Wednesday = 'wednesday'
    Thursday = 'thursday'
    Friday = 'friday'
    Saturday = 'saturday'
    Sunday = 'sunday'


class ScheduleFrequency(Enum):
    Custom = "custom"
    Hourly = "hourly"

@dataclass
class Duration:
    hours: Optional[int] = 0
    minutes: Optional[int] = 0

@dataclass
class Schedule:
    start: time
    scale_type: str
    total_duration: Duration
    target_minReplicas: int
    scale_duration: Optional[Duration] = None
    days: List[str] = field(default_factory=list)

    def __post__init__(self):
        self.validate_days()
        self.validate_scale_type()

    def validate_days(self):
        for day in self.days:
            if day.lower() not in Days:
                raise ValueError(f"Invalidate day: {day}")
            
    def validate_scale_type(self):
        if self.scale_type.lower() not in Scale_Type:
            raise ValueError(f"Invalidate scale type: {self.scale_type}")        

@dataclass
class AppSchedule:
    name: str
    default_minReplicas: int
    schedules: List[Schedule] = field(default_factory=list)

@dataclass
class ScheduleConfig:
    apps: Dict[str, AppSchedule] = field(default_factory=dict)

    def merge(self, other: 'ScheduleConfig') -> 'ScheduleConfig':
        merged_apps = {**self.apps, **other.apps}
        return ScheduleConfig(apps=merged_apps)
    
    def remove(self, other: 'ScheduleConfig') -> 'ScheduleConfig':
        for key in other.apps:
            if key in self.apps:
                del self.apps[key]
        return self

@dataclass
class updateMinReplicasRequest:
    update_required: bool
    target_minReplicas: int