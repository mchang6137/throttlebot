import subprocess
from remote_execution import *
from kubernetes import client, config
import yaml
import os
from poll_cluster_state import *
from run_experiment import *
from collections import defaultdict
import logging
import traceback
import time


def create_workload_deployment(name, workload_size, service_name, additional_args, num_requests = 700, concurrency = 200,
                               thread_count=20, connection_count=100, test_length=5, node_count = 4, ab=True):



    create_and_deploy_workload_deployment(name=name,
                                          replicas=workload_size,
                                          num_requests=num_requests,
                                          concurrency=concurrency,
                                          hostname=get_service_ip(service_name),
                                          port=get_service_port(service_name),
                                          additional_args=additional_args,
                                          node_count=node_count,
                                          thread_count=thread_count,
                                          connection_count=connection_count,
                                          test_length=test_length,
                                          ab=ab)


def scale_workload_deployment(name, workload_size):

    print("Scaling deployment {} to size: {}".format(name, workload_size))

    subprocess.check_output("kubectl scale deployment {} --replicas={}".format(name, workload_size), shell=True)


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


    timeout = time.time() + 20
    while len(pods) != pod_count:

        if time.time() > timeout:
            raise Exception("Deployment Scaling timed out")

        pods = get_all_pods_from_deployment(deployment_name)
    return int(time.time())



def parse_results(deployment_name, num_iterations, offline=False, ab = True):

    all_pod_names = get_all_pods_from_deployment(deployment_name=deployment_name, safe=True)

    pods_data = []

    for pod in all_pod_names:

        pod_data = defaultdict(list)

        for _ in range(num_iterations):

            # print("Iteration: {}".format(_))
            # log = v1.read_namespaced_pod_log(pod, "default", tail_lines=40).split('\n')
            log = None
            timeout = int(time.time())
            broken = False
            while not log:
                try :
                    log = v1.read_namespaced_pod_log(pod, "default", tail_lines=80)
                except Exception as e:
                    broken = True
                    break
                if int(time.time()) - timeout >= 20:
                    broken = True
                    break

            if broken:
                print("Timeout reached in reading log")
                continue

            f = open("output.txt", "w")
            f.write(log)
            f.flush()
            f.close()

            if ab:
                rps_cmd = 'grep \'Requests per second\'  output.txt| tail -1 | awk {{\'print $4\'}}'
                requests_cmd = 'grep \'Complete requests\' output.txt| tail -1 | awk {\'print $3\'}'
                latency_90_cmd = 'grep \'90%\' output.txt | tail -1 |  awk {\'print $2\'}'
                latency_50_cmd = 'grep \'50%\' output.txt | tail -1 |  awk {\'print $2\'}'
                latency_99_cmd = 'grep \'99%\' output.txt | tail -1 |  awk {\'print $2\'}'
                latency_overall_cmd = 'grep \'Time per request\' output.txt | tail -1 |  awk \'NR==1{{print $4}}\''


                try:

                    pod_data['latency_90'].append(float(subprocess.check_output(latency_90_cmd, shell = True).decode('utf-8')[:-1]))

                except Exception as e:
                    print("THE LOG IS " + log + "\n\n\n")
                    traceback.print_exc()

                try:
                    pod_data['latency_99'].append(float(subprocess.check_output(latency_99_cmd, shell = True).decode('utf-8')[:-1]))
                except Exception as e:

                    print("THE LOG IS " + log + "\n\n\n")
                    traceback.print_exc()

                try:
                    NUM_REQUESTS = float(subprocess.check_output(requests_cmd, shell = True).decode('utf-8')[:-1])

                    # print(NUM_REQUESTS)

                    NUM_REQUESTS = int(NUM_REQUESTS)

                    pod_data['latency'].append(float(subprocess.check_output(latency_overall_cmd, shell = True).decode('utf-8')[:-1])*NUM_REQUESTS)

                except Exception as e:

                    print("THE LOG IS " + log + "\n\n\n")
                    traceback.print_exc()

                try:
                    pod_data['latency_50'].append(float(subprocess.check_output(latency_50_cmd, shell = True).decode('utf-8')[:-1]))
                    pod_data['rps'].append(float(subprocess.check_output(rps_cmd, shell = True).decode('utf-8')[:-1]))

                except Exception as e:

                    print("THE LOG IS " + log + "\n\n\n")
                    traceback.print_exc()

                    # ssh_exec(traffic_client, "rm output.txt")
                    #
                    # num_requests = float(log[-27].split(' ')[-1])
                    # pod_data['latency_95'] = float(log[-5].split(' ')[-1])
                    # pod_data['latency_50'] = float(log[-10].split(' ')[-1])
                    # pod_data['latency_overall'] = float(log[-22].split(' ')[-3]) * num_requests
                    # pod_data['rps'] = float(log[-23].split(' ')[-3])
                    # pod_data['latency_99'] = float(log[-3].split(' ')[-1])
                    if num_iterations > 1:
                        sleep(1.5)

            else:
                latency_99_cmd = 'grep \'99%\' output.txt | tail -1 |  awk {\'print $2\'}'
                rps_cmd = 'grep \'Requests/sec\'  output.txt| tail -1 | awk {{\'print $2\'}}'

                try:

                    latency99_result = subprocess.check_output(latency_99_cmd, shell=True).decode('utf-8')[:-1]
                    if latency99_result[-2:] == "ms":
                        latency99_result = float(latency99_result[:-2])
                    else:
                        latency99_result = float(latency99_result[:-1]) * 1000

                    pod_data['latency_99'].append(latency99_result)
                    pod_data['rps'].append(float(subprocess.check_output(rps_cmd, shell = True).decode('utf-8')[:-1]))

                    if num_iterations > 1:
                        sleep(6)

                except Exception as e:
                    print("THE LOG IS " + log + "\n\n\n")
                    traceback.print_exc()

        pod_data_avg = {}
        for key in pod_data:
            lst = pod_data[key]
            if lst:
                pod_data_avg[key] = sum(lst)/len(lst)

        pods_data.append(pod_data_avg)

    # print(pods_data)

    return pods_data



if __name__ == "__main__":

    name = "workload-manager"
    # try:
    #     schedule_workload_change(name, 1, 5)
    # except:
    #     delete_workload_deployment(name)

    schedule_workload_change(name, 1, 5, 'balancer')

    # parse_results(name, 1)