from kubernetes import client, config, watch
import yaml
import os
from datetime import datetime, timedelta, time
import pytz
from scheduler_classes import ScheduleType, ScheduleFrequency, Schedule, ScheduleConfig, Duration, updateMinReplicasRequest

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

def update_min_replicas(namespace: str, hpa_name: str, current_min_replicas: int, target_min_replicas: int, v2):
    print(f'Scheduled Scaler is updating HPA {hpa_name} in {namespace} from {current_min_replicas} to {target_min_replicas}...')
    patch = {
        "spec": {
            "minReplicas": target_min_replicas
        }
    }
    try:
        response = v2.patch_namespaced_horizontal_pod_autoscaler(
            name=hpa_name,
            namespace=namespace,
            body=patch
        )
        print(f"Scheduled Scaler successfully updated minReplicas to {target_min_replicas} for HPA '{hpa_name}' in namespace '{namespace}'")
    except client.exceptions.ApiException as e:
        print(f"Scheduled Scaler exception when updating HPA '{hpa_name}' in namespace '{namespace}': {e}")

def evaluate_schedule(schedule, type: ScheduleType, frequency: ScheduleFrequency, target_app: str, current_replicas: int) -> updateMinReplicasRequest:
    if target_app in schedule:
        app = target_app
        now_ct = datetime.now(central)
        duration = timedelta(hours=schedule[app].duration.hours, minutes=schedule[app].duration.minutes)
        start_time_ct = central.localize(datetime.combine(datetime.today(), schedule[app].start))
        end_time_ct = start_time_ct + duration

        if frequency == ScheduleFrequency.Custom:
            if start_time_ct <= now_ct <= end_time_ct:
                if current_replicas != schedule[app].target_minReplicas:
                    if type == ScheduleType.Everday:
                            print(f'Sending Schedule Event for {app}: minReplicas: {schedule[app].target_minReplicas}')
                            return updateMinReplicasRequest(True, schedule[app].target_minReplicas)

                    if type == ScheduleType.Weekday:
                        if now_ct.weekday() < 5:
                            print(f'Sending Schedule Event for {app}: minReplicas: {schedule[app].target_minReplicas}')
                            return updateMinReplicasRequest(True, schedule[app].target_minReplicas)
            else:
                if current_replicas != schedule[app].default_minReplicas:
                    print(f'Sending Schedule Event for {app}: minReplicas: {schedule[app].default_minReplicas}')
                    return updateMinReplicasRequest(True, schedule[app].default_minReplicas)
        else:
            return updateMinReplicasRequest(False, 1) 

        if frequency == ScheduleFrequency.Hourly:
            time_difference = (now_ct - start_time_ct).total_seconds() / 60
            if start_time_ct <= now_ct <= end_time_ct and (time_difference % 60 == 0 or time_difference % 60 <= schedule[app].scale_duration.minutes):
                if current_replicas != schedule[app].target_minReplicas:                
                    if type == ScheduleType.Everday:
                        print(f'Sending Schedule Event for {app}: minReplicas: {schedule[app].target_minReplicas}')
                        return updateMinReplicasRequest(True, schedule[app].target_minReplicas)
                    
                    if type == ScheduleType.Weekday:
                        if now_ct.weekday() < 5:
                            print(f'Sending Schedule Event for {app}: minReplicas: {schedule[app].target_minReplicas}')
                            return updateMinReplicasRequest(True, schedule[app].target_minReplicas)                            
            else:
                if current_replicas != schedule[app].default_minReplicas:                
                    print(f'Sending Schedule Event for {app}: minReplicas: {schedule[app].default_minReplicas}')
                    return updateMinReplicasRequest(True, schedule[app].default_minReplicas)
        else:
            return updateMinReplicasRequest(False, 1)    
        return updateMinReplicasRequest(False, 1)            
    else:
        return updateMinReplicasRequest(False, 1)                     

def main():
    config.load_kube_config()

    v2 = client.AutoscalingV2Api()

    w = watch.Watch()

    everydaySchedule = get_schedule(environment, ScheduleType.Everday)

    for event in w.stream(v2.list_horizontal_pod_autoscaler_for_all_namespaces):
        hpa = event['object']
        
        if hasattr(hpa.spec, 'min_replicas'):
            hpa_environment = (hpa.metadata.name).split('-')[0]
            if hpa_environment == environment:
                app_name = (hpa.metadata.name).split('-')[1]
                current_replicas = hpa.spec.min_replicas
                print(f"{app_name} - {current_replicas}")
                everydayCustom = evaluate_schedule(everydaySchedule.custom, ScheduleType.Everday, ScheduleFrequency.Custom, app_name, current_replicas)
                everdayHourly = evaluate_schedule(everydaySchedule.hourly, ScheduleType.Everday, ScheduleFrequency.Hourly, app_name, current_replicas)
                if everydayCustom.update_required or everdayHourly.update_required:
                    update_min_replicas(hpa.metadata.namespace, hpa.metadata.name, hpa.spec.min_replicas, everydayCustom.target_minReplicas, v2)
            
if __name__ == '__main__':
    main()