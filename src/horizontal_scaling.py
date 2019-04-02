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

    output = subprocess.check_output("kubectl autoscale deployment {} --cpu-percent={} --min={} --max={}".format(deployment_name,
                                                                                                    cpu_percent,
                                                                                                    min_size,
                                                                                                    max_size),
                            shell=True)

def calculate_deployment_cost(deployment_name, starting_time):

    # cmd = "cat ~/go/data | grep \'" + deployment_name + "\'  | awk {\'print $2\'}"
    # output = (subprocess.check_output(cmd, shell=True)).decode('utf-8')
    # output = output.split('\n')[:-1]
    # pods = list(set(output))

    pod_data = {}

    cpu_quota = get_deployment_cpu_quota(deployment_name)

    pods = get_all_pods_from_deployment(deployment_name=deployment_name, safe=True)

    pods = [str(pod) for pod in pods]

    for pod in pods:
        pod_data[pod] = calculate_pod_cost(pod, cpu_quota, starting_time)

    total_cost = sum(pod_data.values())

    return total_cost

def calculate_pod_cost(pod_name, cpu_quota, starting_time):
    cmd = "cat ~/go/data | grep \'{}\'".format(pod_name)
    output = (subprocess.check_output(cmd, shell=True)).decode('utf-8')
    output = output.split('\n')[:-1]
    output = [str(o) for o in output]

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

def wait_for_autoscaler_steady_state(scale_deployment_name, workload_deployment_name, flag=None, selector=None, utilization = None, ab = True):

    performance_data = []


    label = selector
    if not selector:
        label = scale_deployment_name

    pod_count_every_30_sec= []

    count = 0
    while count < 180:
        if (count % 30 == 0):

            current_pod_count = len(get_all_pods_from_deployment(deployment_name=scale_deployment_name, safe=True))
            print("Current pod count is {}".format(current_pod_count))
            pod_count_every_30_sec.append(current_pod_count)
            # print(calculate_deployment_cost(scale_deployment_name, int(time.time())))
            if (count % 60 == 0):
                performance_data.append({"pods_count": current_pod_count,
                                        "data": parse_results(workload_deployment_name, num_iterations=1, ab=ab)})
            print("done parsing results")

        sleep(1)
        count += 1

        print(count)


    while True:

        try:

            pod_count = len(get_all_pods_from_deployment(deployment_name=scale_deployment_name, safe=True))

            if pod_count_every_30_sec[-4] == pod_count:
                print("Found Steady state")
                return performance_data


            if count % 30 == 0:

                dict_to_add = {}

                dict_to_add["data"] = parse_results(workload_deployment_name, num_iterations=1, ab=ab)

                print("Done parsing results")

                dict_to_add["pods_count"] = len(get_all_pods_from_deployment(scale_deployment_name, safe=True))

                print("Pod count is {}".format(dict_to_add["pods_count"]))

                performance_data.append(dict_to_add)



                pod_count_every_30_sec.append(dict_to_add['pods_count'])

                print(pod_count_every_30_sec)


            sleep(1)

            count += 1

            print(count)

        except Exception as e:
            print(e.args)
            print(e.message)




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

        create_workload_deployment(workload_deployment_name, workload_size, service_name, additional_args, ab = False)

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

        with open('performance_results_{}', 'w') as file:

            performance_data_list.append({"data": pods_data, "utilization": utilization})

            file.write(json.dumps(performance_data_list))

        # Collects and writes cost data
        cost_data = calculate_deployment_cost(scale_deployment_name, time_of_deployment)

        print("Current Cpu Cost: {}".format(cost_data))

        print("Writing cost data to file")

        with open('cost_results', 'w') as file:

            cost_data_list.append({"data": cost_data, "utilization": utilization})

            file.write(json.dumps(cost_data_list))

        with open('performance_results_while_scaling_{}'.format(utilization), 'w') as file:
            file.flush()

        with open('performance_results_while_scaling2_{}'.format(utilization), 'w') as file:
            file.flush()


        subprocess.Popen(['kubectl', 'delete', 'hpa/{}'.format(scale_name)])

        subprocess.Popen(['kubectl', 'delete', 'deployment', scale_deployment_name])

        subprocess.Popen(['kubectl', 'delete', 'deployment', workload_deployment_name])

        sleep(15)

def run_utilization_experiment_variable_workload(scale_deployment_name, workload_deployment_name, service_name, additional_args, workload_size, num_iterations,
                               min_scaleout ,max_scaleout, cpu_cost, node_count=4, label="", ab = True):


    performance_data_list = []
    performance_data_list_2 = []
    cost_data_list = []
    cost_data_list_2 = []

    performance_data_while_scaling = defaultdict(list)
    performance_data_while_scaling2 = defaultdict(list)

    for trial in range(4):

        for utilization in [10, 20, 40, 50]:

            deploying = True
            while deploying:
                try:
                    create_scale_deployment(scale_deployment_name, cpu_cost=cpu_cost)
                    deploying = False
                except:
                    pass

            wait_for_scale_deployment(scale_deployment_name)

            create_workload_deployment(workload_deployment_name, workload_size, service_name, additional_args, node_count=node_count, ab = ab)

            sleep(10)

            create_autoscaler(scale_deployment_name, utilization, min_scaleout, max_scaleout)

            print("Create autoscaler with utilization {}".format(utilization))

            print("Waiting for autoscaler metrics")

            time_of_deployment = wait_for_autoscale_metrics(scale_deployment_name)

            print("Waiting for Autoscaler steady state")

            performance_data_while_scaling[utilization].append(wait_for_autoscaler_steady_state(scale_deployment_name=scale_deployment_name, workload_deployment_name=workload_deployment_name, flag=False,
                                             utilization=utilization, ab=ab))



            # Collects and writes cost data
            cost_data = calculate_deployment_cost(scale_deployment_name, time_of_deployment)

            print("Current Cpu Cost: {}".format(cost_data))

            print("Writing cost data to file")

            with open('cost_results_{}_{}'.format(label, trial), 'w') as file:

                cost_data_list.append({"data": cost_data, "utilization": utilization})

                file.write(json.dumps(cost_data_list))


            # Collects and writes performance data
            pods_data = parse_results(workload_deployment_name, num_iterations=num_iterations, ab=ab)

            print("Writing performance data to file")

            with open('performance_results_{}_{}'.format(label, trial), 'w') as file:
                performance_data_list.append({"data": pods_data, "utilization": utilization})

                file.write(json.dumps(performance_data_list))

            #################################################################################

            # print("Ensuring workload node count is at least {}".format(node_count - 1))

            # ensure_workload_node_count(node_count)

            # sleep(15)

            scale_workload_deployment(workload_deployment_name, workload_size * 7)

            sleep(30)

            timestamp2 = int(time.time())

            print("Waiting for Autoscaler steady state")

            performance_data_while_scaling2[utilization].append(wait_for_autoscaler_steady_state(scale_deployment_name=scale_deployment_name,
                                             workload_deployment_name=workload_deployment_name, flag=True,
                                             utilization=utilization, ab = ab))

            # Collects and writes cost data
            cost_data = calculate_deployment_cost(scale_deployment_name, timestamp2)

            print("Current Cpu Cost: {}".format(cost_data))

            print("Writing cost data to file 2")

            # Collects and writes performance data
            pods_data = parse_results(workload_deployment_name, num_iterations=num_iterations, ab=ab)

            print("Writing performance data to file 2")

            with open('performance_results2_{}_{}'.format(label, trial), 'w') as file:
                performance_data_list_2.append({"data": pods_data, "utilization": utilization})

                file.write(json.dumps(performance_data_list_2))


            with open('cost_results2_{}_{}'.format(label, trial), 'w') as file:
                cost_data_list_2.append({"data": cost_data, "utilization": utilization})

                file.write(json.dumps(cost_data_list_2))


            file = open('performance_results_while_scaling_{}_{}'.format(utilization, label), 'w')
            file.write(json.dumps(performance_data_while_scaling[utilization]))
            file.flush()
            file.close()

            file = open('performance_results_while_scaling2_{}_{}'.format(utilization, label), 'w')
            file.write(json.dumps(performance_data_while_scaling2[utilization]))
            file.flush()
            file.close()

            subprocess.Popen(['kubectl', 'delete', 'hpa/{}'.format(scale_name)])

            subprocess.Popen(['kubectl', 'delete', 'deployment', scale_deployment_name])

            subprocess.Popen(['kubectl', 'delete', 'deployment', workload_deployment_name])

            sleep(25)

def wait_for_scale_deployment(deployment_name):

    ready = False
    while not ready:
        output = subprocess.check_output("kubectl get pods | grep \'" + deployment_name + "\' | awk {\'print $3\'}", shell=True) \
            .decode('utf-8').split("\n")[0]
        if output == "Running":
            ready = True
        sleep(2)

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

    nodes_capacity = get_node_capacity()



    pods_per_node = 2.2

    cpu_quota = None

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
    #
    #

    run_utilization_experiment_variable_workload(scale_deployment_name=scale_name,
                                                 workload_deployment_name=workload_name,
                                                 service_name=service_name,
                                                 additional_args=additional_args,
                                                 workload_size = 2,
                                                 num_iterations=5,
                                                 min_scaleout=10,
                                                 max_scaleout=500,
                                                 cpu_cost=cpu_quota if cpu_quota else str(get_node_capacity() / float(pods_per_node)),
                                                 label="{}podsPerNode".format(pods_per_node),
                                                 node_count=9,
                                                 ab=False)

    # parse_results(workload_name, 2)
    # wait_for_autoscaler_steady_state(scale_name, workload_name)


    # print(calculate_deployment_cost(scale_name, int(time.time())))