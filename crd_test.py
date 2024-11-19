from kubernetes import client, config, watch
import yaml
import os
from datetime import datetime, timedelta, time
import pytz
from scheduler_classes import ScheduleType, ScheduleFrequency, Schedule, ScheduleConfig, Duration, updateMinReplicasRequest
import threading

# Checking environment var
environment = os.getenv('ENVIRONMENT')

if environment is None:
    raise EnvironmentError('ENVIRONMENT variable is not set.')
else:
    print(f'The value for ENVIRONMENT variable is: {environment}')

# Define the timezone for Central Time
central = pytz.timezone('US/Central')
utc = pytz.utc

# Define the API clients
config.load_kube_config()
custom_api = client.CustomObjectsApi()
autoscaling_api = client.AutoscalingV2Api()

# Defining CRD info
group = "scaler.io"
version = "v1alpha1"
plural = "schedules"

def parse_time(time_str: str) -> time:
    hours, minutes = map(int, time_str.split(':'))
    return time(hours, minutes)

def get_app_names(schedule):
    app_names = []
    env_name = schedule.get('metadata', {}).get('labels', {}).get('env', {})
    for item in schedule.get('spec', {}).get('custom', []):
        app_names.append(f"{env_name}-{item.get('name')}")
    for item in schedule.get('spec', {}).get('hourly', []):
        app_names.append(f"{env_name}-{item.get('name')}")
    return app_names

def get_schedule(schedule) -> ScheduleConfig:
    custom = {item.get('name'): Schedule(
        name = item.get('name'),
        start = parse_time(item.get('start')),
        total_duration = Duration(item.get('total-duration')),
        target_minReplicas = item.get('target-minReplicas'),
        default_minReplicas = item.get('default-minReplicas'),
        days = item.get('days')
    ) for item in schedule.get('spec', {}).get('custom', [])}

    hourly = {item.get('name'): Schedule(
        name = item.get('name'),
        start = parse_time(item.get('start')),
        total_duration = Duration(item.get('total-duration')),
        target_minReplicas = item.get('target-minReplicas'),
        default_minReplicas = item.get('default-minReplicas'),
        days = item.get('days')
    ) for item in schedule.get('spec', {}).get('hourly', [])}

    return ScheduleConfig(custom=custom, hourly=hourly)

def watch_hpa(stop_event, app_names, schedule_data):
    hpa_watch = watch.Watch()
    for hpa_event in hpa_watch.stream(autoscaling_api.list_horizontal_pod_autoscaler_for_all_namespaces):
        if stop_event.is_set():
            break
        hpa = hpa_event['object']
        hpa_name = f"{(hpa.metadata.name).split('-')[0]}-{(hpa.metadata.name).split('-')[1]}"
        if hpa_name in app_names:
           # print(f"HPA Event: {hpa_event['type']} - HPA: {hpa_name} - Current Replicas: {hpa.status.current_replicas}") 
           app = (hpa.metadata.name).split('-')[1]
           print(schedule_data.custom)
           current_replicas = hpa.status.current_replicas
           target_replicas = schedule_data.custom[app].target_minReplicas
           print(f'App: {app}, Current Replicas: {current_replicas}, Target Replias: {target_replicas}')
           

def watch_schedules():
    app_names_set = set()
    stop_event = threading.Event()
    hpa_thread = None
    w = watch.Watch()
    schedule_data = ScheduleConfig()
    for event in w.stream(custom_api.list_namespaced_custom_object, group, version, "kube-system", plural):
        schedule = event['object']
        event_type = event['type']
        app_names = get_app_names(schedule)
        inital_schedule = get_schedule(schedule)

        if event_type in ["ADDED", "MODIFIED"]:
            app_names_set.update(app_names)
            schedule_data = schedule_data.merge(inital_schedule)
        elif event_type == "DELETED":
            app_names_set.difference_update(app_names)
            schedule_data = schedule_data.remove(inital_schedule)

        print(f"Event: {event_type} - Schedule: {schedule['metadata']['name']}")
        print(f"App names: {app_names_set}")

        if hpa_thread is not None:
            stop_event.set()
            hpa_thread.join()
            stop_event.clear()
        hpa_thread = threading.Thread(target=watch_hpa, args=(stop_event, app_names_set, schedule_data))
        hpa_thread.start()

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
    watch_schedules()

    # api_instance = client.CustomObjectsApi()

    # # Watching for changes to the Schedule CRD
    # crdWatch = watch.Watch()
    # for event in crdWatch.stream(api_instance.list_namespaced_custom_object, group, version, "kube-system", plural):
    #     crd = event['object']
    #     event_type = event['type']
    #     name = crd['metadata']['name']
    #     spec = crd['spec']

    #     print(f"Event: {event_type} - Schedule: {name}")
    #     print(f"Spec: {spec}")

    #     v2 = client.AutoscalingV2Api()

    #     w = watch.Watch()

    #     everydaySchedule = get_schedule(environment, ScheduleType.Everday)

    #     for event in w.stream(v2.list_horizontal_pod_autoscaler_for_all_namespaces):
    #         hpa = event['object']
            
    #         if hasattr(hpa.spec, 'min_replicas'):
    #             hpa_environment = (hpa.metadata.name).split('-')[0]
    #             if hpa_environment == environment:
    #                 app_name = (hpa.metadata.name).split('-')[1]
    #                 current_replicas = hpa.spec.min_replicas
    #                 print(f"{app_name} - {current_replicas}")
    #                 everydayCustom = evaluate_schedule(everydaySchedule.custom, ScheduleType.Everday, ScheduleFrequency.Custom, app_name, current_replicas)
    #                 everdayHourly = evaluate_schedule(everydaySchedule.hourly, ScheduleType.Everday, ScheduleFrequency.Hourly, app_name, current_replicas)
    #                 if everydayCustom.update_required or everdayHourly.update_required:
    #                     update_min_replicas(hpa.metadata.namespace, hpa.metadata.name, hpa.spec.min_replicas, everydayCustom.target_minReplicas, v2)
            
if __name__ == '__main__':
    main()