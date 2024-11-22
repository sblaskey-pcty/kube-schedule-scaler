from kubernetes import client, config, watch
from datetime import datetime, timedelta, time
import pytz
from scheduler_classes import ScheduleType, ScheduleFrequency, AppSchedule, Schedule, ScheduleConfig, Duration, updateMinReplicasRequest
import threading

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
    for item in schedule.get('spec', []):
        app_names.append(f"{env_name}-{item.get('name')}")
    return app_names

def get_schedule(schedule) -> ScheduleConfig:
    env_name = schedule.get('metadata', {}).get('labels', {}).get('env', {})

    schedule_data = {f"{env_name}-{item.get('name')}": AppSchedule(
        name = item.get('name'),
        default_minReplicas = item.get('default-minReplicas'),        
        schedules = [Schedule(
            start = parse_time(schedule.get('start')),
            scale_type = schedule.get('scale-type'),            
            total_duration = Duration(
                hours=schedule.get('total-duration').get('hours', 0),
                minutes=schedule.get('total-duration').get('minutes', 0)
                ),
            scale_duration = Duration(
                minutes=schedule.get('scale-duration', {}).get('minutes', 0)
            ),
            target_minReplicas = schedule.get('target-minReplicas'),
            days = schedule.get('days')
        ) for schedule in item.get('schedules', [])]
    ) for item in schedule.get('spec', [])}

    return ScheduleConfig(apps=schedule_data)

def watch_hpa(stop_event, app_names, schedule_data):
    hpa_watch = watch.Watch()
    for hpa_event in hpa_watch.stream(autoscaling_api.list_horizontal_pod_autoscaler_for_all_namespaces):
        if stop_event.is_set():
            break
        hpa = hpa_event['object']
        hpa_name = f"{(hpa.metadata.name).split('-')[0]}-{(hpa.metadata.name).split('-')[1]}"
        if hpa_name in app_names:
            default_minReplicas = schedule_data.apps[hpa_name].default_minReplicas
            for schedule in schedule_data.apps[hpa_name].schedules:
                current_minReplicas = hpa.spec.min_replicas
                current_replicas = hpa.status.current_replicas
                target_replicas = schedule.target_minReplicas
                print(f'Event-type: {hpa_event["type"]}, App: {hpa_name}, Running Replicas: {current_replicas}, Current minReplicas: {current_minReplicas}, Target minReplicas: {target_replicas}')
                evulation_results = evaluate_schedule(schedule, hpa_name, current_minReplicas, default_minReplicas)
                print(f"Evulation Results: {evulation_results}")

            

def watch_schedules():
    app_names_set = set()
    schedule_names_set = set()
    stop_event = threading.Event()
    hpa_thread = None
    w = watch.Watch()
    schedule_data = ScheduleConfig()
    for event in w.stream(custom_api.list_namespaced_custom_object, group, version, "kube-system", plural):
        schedule = event['object']
        event_type = event['type']
        schedule_name = event['object']['metadata']['name']
        app_names = get_app_names(schedule)
        initial_schedule = get_schedule(schedule)
        print(schedule_name)
        print(schedule_names_set)
        if event_type in ["ADDED"]:
            duplicate = False
            for app in app_names:
                if app in app_names_set:
                    print(f"Schedule for {app} already exists. Skipping")
                    duplicate = True
            if duplicate == False:
                schedule_names_set.add(schedule_name)
                app_names_set.update(app_names)
                schedule_data = schedule_data.merge(initial_schedule)
        elif event_type in ["MODIFIED"]:
            app_names_set.update(app_names)
            schedule_data = schedule_data.merge(initial_schedule)
        elif event_type == "DELETED":
            if schedule_name in schedule_names_set:
                app_names_set.difference_update(app_names)
                schedule_names_set.remove(schedule_name)
                schedule_data = schedule_data.remove(initial_schedule)

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

def evaulate_days(day_type: str, now_ct: datetime) -> bool:
    if day_type == 'everyday':
        return True
    
    if day_type == 'weekday':
        if now_ct.weekday() < 5:
            return True
        
    if day_type == 'weekend':
        if now_ct.weekday() >= 5:
            return True
        
    if day_type == 'monday':
        if now_ct.weekday() == 0:
            return True
        
    if day_type == 'tuesday':
        if now_ct.weekday() == 1:
            return True
        
    if day_type == 'wednesday':
        if now_ct.weekday() == 2:
            return True
    
    if day_type == 'thursday':
        if now_ct.weekday() == 3:
            return True
        
    if day_type == 'friday':
        if now_ct.weekday() == 4:
            return True
        
    if day_type == 'saturday':
        if now_ct.weekday() == 5:
            return True
        
    if day_type == 'sunday':
        if now_ct.weekday() == 6:
            return True


def evaluate_schedule(schedule: Schedule, target_app: str, current_minReplicas: int, default_minReplicas: int) -> updateMinReplicasRequest:
    app = target_app
    now_ct = datetime.now(central)
    duration = timedelta(hours=schedule.total_duration.hours, minutes=schedule.total_duration.minutes)
    start_time_ct = central.localize(datetime.combine(datetime.today(), schedule.start))
    end_time_ct = start_time_ct + duration

    if schedule.scale_type == 'custom':
        if start_time_ct <= now_ct <= end_time_ct:
            if current_minReplicas != schedule.target_minReplicas:
                for day_type in schedule.days:
                    result = evaulate_days(day_type, now_ct)
                    if result:
                        print(f'Sending Schedule Event for {app}: current_minReplicas: {current_minReplicas}, target_minReplicas: {schedule.target_minReplicas}')
                        return updateMinReplicasRequest(True, schedule.target_minReplicas)
                    else:
                        return updateMinReplicasRequest(False, 1)
            else:
                return updateMinReplicasRequest(False, 1)                
        else:
            if current_minReplicas != default_minReplicas:
                print(f'Sending Schedule Event for {app}: current_minReplicas: {current_minReplicas}, target_minReplicas: {default_minReplicas}')
                return updateMinReplicasRequest(True, schedule[app].default_minReplicas)
            else:
                return updateMinReplicasRequest(False, 1)
    else:
        return updateMinReplicasRequest(False, 1)


                    


# def evaluate_schedule(schedule, type: ScheduleType, frequency: ScheduleFrequency, target_app: str, current_replicas: int) -> updateMinReplicasRequest:
#     if target_app in schedule:
#         app = target_app
#         now_ct = datetime.now(central)
#         duration = timedelta(hours=schedule[app].duration.hours, minutes=schedule[app].duration.minutes)
#         start_time_ct = central.localize(datetime.combine(datetime.today(), schedule[app].start))
#         end_time_ct = start_time_ct + duration

#         if frequency == ScheduleFrequency.Custom:
#             if start_time_ct <= now_ct <= end_time_ct:
#                 if current_replicas != schedule[app].target_minReplicas:
#                     if type == ScheduleType.Everday:
#                             print(f'Sending Schedule Event for {app}: minReplicas: {schedule[app].target_minReplicas}')
#                             return updateMinReplicasRequest(True, schedule[app].target_minReplicas)

#                     if type == ScheduleType.Weekday:
#                         if now_ct.weekday() < 5:
#                             print(f'Sending Schedule Event for {app}: minReplicas: {schedule[app].target_minReplicas}')
#                             return updateMinReplicasRequest(True, schedule[app].target_minReplicas)
#             else:
#                 if current_replicas != schedule[app].default_minReplicas:
#                     print(f'Sending Schedule Event for {app}: minReplicas: {schedule[app].default_minReplicas}')
#                     return updateMinReplicasRequest(True, schedule[app].default_minReplicas)
#         else:
#             return updateMinReplicasRequest(False, 1) 

#         if frequency == ScheduleFrequency.Hourly:
#             time_difference = (now_ct - start_time_ct).total_seconds() / 60
#             if start_time_ct <= now_ct <= end_time_ct and (time_difference % 60 == 0 or time_difference % 60 <= schedule[app].scale_duration.minutes):
#                 if current_replicas != schedule[app].target_minReplicas:                
#                     if type == ScheduleType.Everday:
#                         print(f'Sending Schedule Event for {app}: minReplicas: {schedule[app].target_minReplicas}')
#                         return updateMinReplicasRequest(True, schedule[app].target_minReplicas)
                    
#                     if type == ScheduleType.Weekday:
#                         if now_ct.weekday() < 5:
#                             print(f'Sending Schedule Event for {app}: minReplicas: {schedule[app].target_minReplicas}')
#                             return updateMinReplicasRequest(True, schedule[app].target_minReplicas)                            
#             else:
#                 if current_replicas != schedule[app].default_minReplicas:                
#                     print(f'Sending Schedule Event for {app}: minReplicas: {schedule[app].default_minReplicas}')
#                     return updateMinReplicasRequest(True, schedule[app].default_minReplicas)
#         else:
#             return updateMinReplicasRequest(False, 1)    
#         return updateMinReplicasRequest(False, 1)            
#     else:
#         return updateMinReplicasRequest(False, 1)                     

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