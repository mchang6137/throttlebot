import subprocess
from remote_execution import *
from kubernetes import client, config
import yaml
import os
from poll_cluster_state import *
from run_experiment import *
from collections import defaultdict
import logging


def create_workload_deployment(name, workload_size, service_name, additional_args):
    ssh_client = get_client(get_master())

    create_and_deploy_workload_deployment(name,
                                           workload_size,
                                          350,
                                          150,
                                          get_service_ip(service_name),
                                          get_service_port(service_name),
                                          additional_args)


def scale_workload_deployment(name, workload_size):
    ssh_client = get_client(get_master())

    ssh_exec(ssh_client, "kubectl scale deployment {} --replicas={}".format(name, workload_size))


def schedule_workload_change(deployment_name, num_iterations, max_workload_size, service_name):


    create_workload_deployment(deployment_name, 1, service_name)

    wait_for_pods_to_be_deployed(deployment_name, 1)

    parse_results(deployment_name, num_iterations)

    for workload_size in range(2, max_workload_size):

        scale_workload_deployment(deployment_name, workload_size)

        print("Scaled deployment to size {}".format(workload_size))

        wait_for_pods_to_be_deployed(deployment_name, workload_size)

        parse_results(deployment_name, num_iterations)


def wait_for_pods_to_be_deployed(deployment_name, pod_count):
    pods = get_all_pods_from_deployment(deployment_name)


    import time
    timeout = time.time() + 20
    while len(pods) != pod_count:

        if time.time() > timeout:
            raise Exception("Deployment Scaling timed out")

        pods = get_all_pods_from_deployment(deployment_name)
    return int(time.time())



def parse_results(deployment_name, num_iterations):

    all_pod_names = get_all_pods_from_deployment(deployment_name)

    pods_data = []

    for pod in all_pod_names:

        # print("did i get here?")

        try:

            pod_data = defaultdict(list)

            for _ in range(num_iterations):

                log = v1.read_namespaced_pod_log(pod, "default", tail_lines=40)
                with open("output.txt", "w") as f:
                    f.write(log)

                rps_cmd = 'grep \'Requests per second\'  output.txt| tail -1 | awk {{\'print $4\'}}'
                requests_cmd = 'grep \'Complete requests\' output.txt| tail -1 | awk {\'print $3\'}'
                latency_90_cmd = 'grep \'90%\' output.txt | tail -1 |  awk {\'print $2\'}'
                latency_50_cmd = 'grep \'50%\' output.txt | tail -1 |  awk {\'print $2\'}'
                latency_99_cmd = 'grep \'99%\' output.txt | tail -1 |  awk {\'print $2\'}'
                latency_overall_cmd = 'grep \'Time per request\' output.txt | tail -1 |  awk \'NR==1{{print $4}}\''

                pod_data['latency_90'].append(subprocess.check_output(latency_90_cmd, shell = True).decode('utf-8')[:-1])
                pod_data['latency_99'].append(subprocess.check_output(latency_99_cmd, shell = True).decode('utf-8')[:-1])

                NUM_REQUESTS = float(subprocess.check_output(requests_cmd, shell = True).decode('utf-8')[:-1])

                # print(NUM_REQUESTS)

                # NUM_REQUESTS = int(NUM_REQUESTS)

                pod_data['latency'].append(float(subprocess.check_output(latency_overall_cmd, shell = True).decode('utf-8')[:-1])*NUM_REQUESTS)
                pod_data['latency_50'].append(subprocess.check_output(latency_50_cmd, shell = True).decode('utf-8')[:-1])
                pod_data['rps'].append(subprocess.check_output(rps_cmd, shell = True).decode('utf-8')[:-1])

                # ssh_exec(traffic_client, "rm output.txt")


            pods_data.append(pod_data)

        except:
            pass


    return pods_data



if __name__ == "__main__":

    name = "workload-manager"
    # try:
    #     schedule_workload_change(name, 1, 5)
    # except:
    #     delete_workload_deployment(name)

    schedule_workload_change(name, 1, 5, 'balancer')

    # parse_results(name, 1)