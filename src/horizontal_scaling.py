import subprocess
from remote_execution import *
from kubernetes import client, config
import yaml
import os
from poll_cluster_state import *
from run_experiment import *
from collections import defaultdict
import logging
from workload_manager import *
import json


def create_autoscaler(deployment_name, cpu_percent, min_size, max_size):
    ssh_client = get_client(get_master())
    ssh_exec(ssh_client, "kubectl autoscale deployment {} --cpu-percent={} --min={} --max={}".format(deployment_name,
                                                                                                    cpu_percent,
                                                                                                    min_size,
                                                                                                    max_size))

def calculate_deployment_cost(deployment_name, starting_time):

    cmd = "cat ~/go/data | grep \'" + deployment_name + "\'  | awk {\'print $2\'}"
    output = (subprocess.check_output(cmd, shell=True)).decode('utf-8')
    output = output.split('\n')[:-1]
    pods = list(set(output))

    pod_data = {}

    cpu_quota = get_deployment_cpu_quota(deployment_name)

    for pod in pods:
        pod_data[pod] = calculate_pod_cost(pod, cpu_quota, starting_time)

    total_cost = sum(pod_data.values())

    return total_cost

def calculate_pod_cost(pod_name, cpu_quota, starting_time):
    cmd = "cat ~/go/data | grep \'{}\'".format(pod_name)
    output = (subprocess.check_output(cmd, shell=True)).decode('utf-8')
    output = output.split('\n')[:-1]
    cost = 0
    if output[-1].split(" ")[0] == "Delete":
        time_stopped = int(output[1].split(" ")[2])

        if time_stopped < starting_time:
            return 0

        cost = int(output[1].split(" ")[2]) - starting_time
    else:
        if output[0].split(" ")[0] == "Add" and int(output[0].split(" ")[2]) > starting_time:
            cost = int(time.time()) - int(output[0].split(" ")[2])
        else:
            cost = int(time.time()) - starting_time

    return cost * cpu_quota

def wait_for_autoscaler_steady_state(scale_deployment_name, workload_deployment_name, flag=None, selector=None, utilization = None):

    performance_data = []


    label = selector
    if not selector:
        label = scale_deployment_name

    pod_count_every_min = []

    starting_time = int(subprocess.check_output('kubectl get hpa | tail -1 | awk {\'print $9 \'}', shell=True).decode('utf-8')[:-2])
    count = 0

    if starting_time < 4:

        while starting_time < 4:
            starting_time = int(subprocess.check_output('kubectl get hpa | tail -1 | awk {\'print $9 \'}',
                                                    shell=True).decode('utf-8')[:-2])
            if (count % 30 == 0):
                pod_count_every_min.append(int(subprocess.check_output('kubectl get hpa | tail -1 | awk {\'print $8 \'}', shell=True).decode('utf-8')[:-1]))
            sleep(2)
            count += 1




    while True:

        pod_count = int(subprocess.check_output('kubectl get hpa | tail -1 | awk {\'print $8 \'}', shell=True)
                        .decode('utf-8')[:-1])

        if pod_count[-4] == pod_count:
            print("Found Steady state")
            return int(time.time())


        if count % 30 == 0:

            performance_data.append({"data": parse_results(workload_deployment_name, 1),
                                     "pods_count": len(get_all_pods_from_deployment(scale_deployment_name, label))})

            pod_count_every_min.append(int(
                subprocess.check_output('kubectl get hpa | tail -1 | awk {\'print $8 \'}', shell=True).decode('utf-8')[
                :-1]))

        if count % 90 == 0:
            print("Writing intermediate data")


            filename = "performance_results_while_scaling"

            if flag:
                filename = "performance_results_while_scaling2"

            if utilization:
                filename += "_{}".format(utilization)


            file = open(filename, 'w')

            performance_data.append({"data": parse_results(workload_deployment_name, 1), "pods_count": len(get_all_pods_from_deployment(scale_deployment_name, selector))})

            file.write(json.dumps(performance_data))

            file.flush()

            file.close()


        sleep(2)
        count += 1




def run_workload_experiment(deployment_name, num_iterations, max_workload_size, service_name):

    #Creates initial workload deployment
    create_workload_deployment(deployment_name, 1, service_name)

    time_of_deployment = wait_for_pods_to_be_deployed(deployment_name, 1)

    #Collects and writes performance data
    pods_data = parse_results(deployment_name, num_iterations)

    with open('performance_results', 'w') as file:

        pods_data = [{"data": pods_data, "workload_size": 1}]

        file.write(json.dumps(pods_data))


    #Collects and writes cost data
    cost_data = calculate_deployment_cost(deployment_name, time_of_deployment)

    print("Current Cpu Cost: {}".format(cost_data))

    with open('cost_results', 'w') as file:

        cost_data = [{"data": cost_data, "workload_size": 1}]

        file.write(json.dumps(cost_data))


    for workload_size in range(2, max_workload_size):

        #Scales Workload Deployment
        scale_workload_deployment(deployment_name, workload_size)

        print("Scaled deployment to size {}".format(workload_size))

        time_of_deployment = wait_for_pods_to_be_deployed(deployment_name, workload_size)

        #Collects and writes performance data
        pods_data = parse_results(deployment_name, num_iterations)

        with open('performance_results', 'w') as file:

            pods_data.append({"data": pods_data, "workload_size": workload_size})

            file.write(json.dumps(pods_data))

        wait_for_autoscaler_steady_state(deployment_name)

        # Collects and writes cost data
        cost_data = calculate_deployment_cost(deployment_name, time_of_deployment)

        print("Current Cpu Cost: {}".format(cost_data))

        with open('cost_results', 'w') as file:

            cost_data.append({"data": cost_data, "workload_size": workload_size})

            file.write(json.dumps(cost_data))

def run_utilization_experiment(scale_deployment_name, workload_deployment_name, service_name, additional_args, workload_size, num_iterations,
                               min_scaleout ,max_scaleout):


    performance_data_list = []
    cost_data_list = []

    for utilization in [20]:

        subprocess.Popen(['kubectl', 'create', '-f', 'manifests/{}.yaml'.format(scale_deployment_name)])

        create_workload_deployment(workload_deployment_name, workload_size, service_name, additional_args)

        sleep(10)

        create_autoscaler(scale_deployment_name, utilization, min_scaleout, max_scaleout)

        print("Create autoscaler with utilization {}".format(utilization))

        print("Waiting for autoscaler metrics")

        time_of_deployment = wait_for_autoscale_metrics(scale_deployment_name)

        print("Waiting for Autoscaler steady state")

        wait_for_autoscaler_steady_state(scale_deployment_name, workload_deployment_name)

        #Collects and writes performance data
        pods_data = parse_results(workload_deployment_name, num_iterations)

        print("Writing performance data to file")

        with open('performance_results', 'w') as file:

            performance_data_list.append({"data": pods_data, "utilization": utilization})

            file.write(json.dumps(performance_data_list))

        # Collects and writes cost data
        cost_data = calculate_deployment_cost(scale_deployment_name, time_of_deployment)

        print("Current Cpu Cost: {}".format(cost_data))

        print("Writing cost data to file")

        with open('cost_results', 'w') as file:

            cost_data_list.append({"data": cost_data, "utilization": utilization})

            file.write(json.dumps(cost_data_list))

        subprocess.Popen(['kubectl', 'delete', 'hpa/{}'.format(scale_name)])

        subprocess.Popen(['kubectl', 'delete', 'deployment', scale_deployment_name])

        subprocess.Popen(['kubectl', 'delete', 'deployment', workload_deployment_name])

        sleep(15)

def run_utilization_experiment_variable_workload(scale_deployment_name, workload_deployment_name, service_name, additional_args, workload_size, num_iterations,
                               min_scaleout ,max_scaleout):


    performance_data_list = []
    cost_data_list = []

    for utilization in [10, 20, 40]:

        subprocess.Popen(['kubectl', 'create', '-f', 'manifests/{}.yaml'.format(scale_deployment_name)])

        create_workload_deployment(workload_deployment_name, workload_size, service_name, additional_args)

        sleep(10)

        create_autoscaler(scale_deployment_name, utilization, min_scaleout, max_scaleout)

        print("Create autoscaler with utilization {}".format(utilization))

        print("Waiting for autoscaler metrics")

        time_of_deployment = wait_for_autoscale_metrics(scale_deployment_name)

        print("Waiting for Autoscaler steady state")

        wait_for_autoscaler_steady_state(scale_deployment_name=scale_deployment_name, workload_deployment_name=workload_deployment_name, flag=False,
                                         utilization=utilization)

        #Collects and writes performance data
        pods_data = parse_results(workload_deployment_name, num_iterations)

        print("Writing performance data to file")

        with open('performance_results', 'w') as file:

            performance_data_list.append({"data": pods_data, "utilization": utilization})

            file.write(json.dumps(performance_data_list))

        # Collects and writes cost data
        cost_data = calculate_deployment_cost(scale_deployment_name, time_of_deployment)

        print("Current Cpu Cost: {}".format(cost_data))

        print("Writing cost data to file")

        with open('cost_results', 'w') as file:

            cost_data_list.append({"data": cost_data, "utilization": utilization})

            file.write(json.dumps(cost_data_list))


        #################################################################################

        scale_workload_deployment(workload_deployment_name, workload_size * 4)

        timestamp2 = int(time.time())

        wait_for_autoscaler_steady_state(scale_deployment_name=scale_deployment_name,
                                         workload_deployment_name=workload_deployment_name, flag=True,
                                         utilization=utilization)

        # Collects and writes performance data
        pods_data = parse_results(workload_deployment_name, num_iterations)

        print("Writing performance data to file 2")

        with open('performance_results2', 'w') as file:
            performance_data_list.append({"data": pods_data, "utilization": utilization})

            file.write(json.dumps(performance_data_list))

        # Collects and writes cost data
        cost_data = calculate_deployment_cost(scale_deployment_name, timestamp2)

        print("Current Cpu Cost: {}".format(cost_data))

        print("Writing cost data to file 2")

        with open('cost_results2', 'w') as file:
            cost_data_list.append({"data": cost_data, "utilization": utilization})

            file.write(json.dumps(cost_data_list))




        subprocess.Popen(['kubectl', 'delete', 'hpa/{}'.format(scale_name)])

        subprocess.Popen(['kubectl', 'delete', 'deployment', scale_deployment_name])

        subprocess.Popen(['kubectl', 'delete', 'deployment', workload_deployment_name])

        sleep(15)



def wait_for_autoscale_metrics(deployment_name):
    ready = False
    try:
        while not ready:
            output = subprocess.check_output("kubectl describe hpa/{}".format(deployment_name) + "| grep \"<unknown>\""
                                             ,shell=True).decode('utf-8')
            sleep(5)
    except:
        return int(time.time())



if __name__ == "__main__":

    scale_name = "node-app"

    workload_name = "workload-manager"

    service_name = "node-app"

    additional_args = ""

    delete = False
    try:
        subprocess.Popen(['kubectl', 'delete', 'deployment', scale_name])
        delete = True
    except:
        pass

    try:
        subprocess.Popen(['kubectl', 'delete', 'deployment', workload_name])
        delete = True
    except:
        pass

    try:
        subprocess.Popen(['kubectl', 'delete', 'hpa/{}'.format(scale_name)])
        delete = True
    except:
        pass

    if delete:
        sleep(20)

    # try:
    #     subprocess.Popen(['kubectl', 'create', '-f', 'manifests/{}.yaml'.format(scale_name)])
    # except:
    #     pass
    #
    # workload_size = 12
    #
    # create_autoscaler(scale_name, 10, 10, 200)
    # create_workload_deployment(workload_name, workload_size, service_name)
    # wait_for_pods_to_be_deployed(workload_name, workload_size)
    # wait_for_autoscale_metrics(scale_name)
    # current_time = int(time.time())
    #
    #
    #
    # while True:
    #     print("Current cpu cost: {}".format(calculate_deployment_cost(scale_name, current_time)))
    #     sleep(10)

    run_utilization_experiment_variable_workload(scale_name, workload_name, service_name, additional_args, 10, 1, 10, 500)
    # wait_for_autoscaler_steady_state(scale_name, workload_name)

