import yaml
import os
from datetime import datetime, timedelta, time
import pytz
from scheduler_classes import ScheduleType, ScheduleFrequency, Schedule, ScheduleConfig, Duration


# Checking environment var
environment = os.getenv('ENVIRONMENT')

if environment is None:
    raise EnvironmentError('ENVIRONMENT variable is not set.')
else:
    print(f'The value for ENVIRONMENT variable is: {environment}')

# Define the timezone for Central Time
central = pytz.timezone('US/Central')
utc = pytz.utc
 

def parse_time(time_str: str) -> time:
    hours, minutes = map(int, time_str.split(':'))
    return time(hours, minutes)

def get_schedule(environment, scheduleType: ScheduleType):
    with open(f'./schedule/{environment}/{scheduleType.value}.yaml', 'r') as file:
        schedule = yaml.safe_load(file)
    file.close()

    custom = {list(item.keys())[0]: Schedule(
        start=parse_time(item[list(item.keys())[0]]['start']),
        duration=Duration(**item[list(item.keys())[0]]['duration']),
        target_minReplicas=item[list(item.keys())[0]]['target_minReplicas'],
        default_minReplicas=item[list(item.keys())[0]]['default_minReplicas']
    ) for item in schedule['custom']}

    hourly = {list(item.keys())[0]: Schedule(
        start=parse_time(item[list(item.keys())[0]]['start']),
        scale_duration=Duration(**item[list(item.keys())[0]]['scale_duration']),
        duration=Duration(**item[list(item.keys())[0]]['duration']),
        target_minReplicas=item[list(item.keys())[0]]['target_minReplicas'],
        default_minReplicas=item[list(item.keys())[0]]['default_minReplicas']
    ) for item in schedule['hourly']}

    return ScheduleConfig(custom=custom, hourly=hourly)

def update_min_replicas(schedule, env, type: ScheduleType):
    for app in schedule:
        for name, data in app.items():
            now_ct = datetime.now(central)
            start_time_str, hours, minutes, min_replicas_true, min_replicas_false = data.split(',')
            start_time = datetime.strptime(start_time_str, '%H:%M')
            duration = timedelta(hours=int(hours), minutes=int(minutes))

            # Define the start time in Central Time
            start_time_ct = central.localize(datetime.combine(now_ct.date(), start_time.time()))

            # Calculate the end time
            end_time_ct = start_time_ct + duration

            # Check if the current time is within the range depending on type
            if start_time_ct <= now_ct <= end_time_ct:
                if type == 'weekdays':
                    if now_ct.weekday() < 5:
                        print(f'Updating min replicas to {min_replicas_true} for {name} in {env}')

                if type == 'everyday':
                    print(f'Updating min replicas to {min_replicas_true} for {name} in {env}')
            else:
                print(f'Updating min replicas to {min_replicas_false} for {name} in {env}')

def evalutate_schedule(schedule, type: ScheduleType, frequency: ScheduleFrequency, target_app: str):
    if target_app in schedule:
        app = target_app
        now_ct = datetime.now(central)
        duration = timedelta(hours=schedule[app].duration.hours, minutes=schedule[app].duration.minutes)
        start_time_ct = central.localize(datetime.combine(datetime.today(), schedule[app].start))
        end_time_ct = start_time_ct + duration

        if frequency == ScheduleFrequency.Custom:
            if start_time_ct <= now_ct <= end_time_ct:
                if type == ScheduleType.Everday:
                    print(f'Sending Schedule Event for {app}: minReplicas: {schedule[app].target_minReplicas}')

                if type == ScheduleType.Weekday:
                    if now_ct.weekday() < 5:
                        print(f'Sending Schedule Event for {app}: minReplicas: {schedule[app].target_minReplicas}')
            else:
                print(f'Sending Schedule Event for {app}: minReplicas: {schedule[app].default_minReplicas}')

        if frequency == ScheduleFrequency.Hourly:
            time_difference = (now_ct - start_time_ct).total_seconds() / 60
            if start_time_ct <= now_ct <= end_time_ct and (time_difference % 60 == 0 or time_difference % 60 <= 15):
                if type == ScheduleType.Everday:
                    print(f'Sending Schedule Event for {app}: minReplicas: {schedule[app].target_minReplicas}')
                
                if type == ScheduleType.Weekday:
                    if now_ct.weekday() < 5:
                        print(f'Sending Schedule Event for {app}: minReplicas: {schedule[app].target_minReplicas}')

            else:
                print(f'Sending Schedule Event for {app}: minReplicas: {schedule[app].default_minReplicas}')



def main():
    everydaySchedule = get_schedule(environment, ScheduleType.Everday)
    evalutate_schedule(everydaySchedule.custom, ScheduleType.Everday, ScheduleFrequency.Custom)
    evalutate_schedule(everydaySchedule.hourly, ScheduleType.Everday, ScheduleFrequency.Hourly)
   # print(list(everdaySchedule.custom.keys()))
   # print(list(everdaySchedule.hourly.keys()))

    weekdaySchedule = get_schedule(environment, ScheduleType.Weekday)
   # print(list(weekdaySchedule.custom.keys()))
   # print(list(weekdaySchedule.hourly.keys()))

if __name__ == '__main__':
    main()
