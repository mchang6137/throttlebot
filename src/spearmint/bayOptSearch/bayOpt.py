import argparse
import csv
import ConfigParser
import time
import numpy as np

import redis.client
import subprocess
import os
import sys
currentDirectory = os.getcwd()
sys.path.append("/Users/rahulbalakrishnan/Desktop/throttlebot/src")
import modify_resources as resource_modifier
import run_experiment
import filter_policy, instance_specs
import remote_execution as re
from mr import MR


# os.chdir(currentDirectory)

# parser = argparse.ArgumentParser()
# parser.add_argument("--spearmint_config", help="Spearmint")
# args = parser.parse_args()


# def parse_config_file():
#     workload_config['type'] = 'spark-ml-matrix'
#     workload_config['request_generator'] = [1]  # request generator
#     workload_config['additional_args'] = {'container_id': 'blah'}
#     workload_config['num_trials'] = 5
#     return workload_config
#
#
# workload_config = parse_config_file()

def load_config():
    d = {}
    with open("/Users/rahulbalakrishnan/Desktop/throttlebot/src/spearmint/bayOptSearch/workload_config") as f:
        for line in f:
            try:
               (key, val) = line.split(" = ")
               d[key] = val
            except:
                key = line.split(" =")[0]
                d[key] = None
                pass

    return d

workload_config = load_config()

past_results = {}


def main(job_id, params):


    # return 1
    return explore_spearmint(workload_config, params)




def explore_spearmint(workload_config, params):

    redis_db = redis.StrictRedis(host='0.0.0.0', port=6379, db=0)
    experiment_trials = workload_config['num_trials'] if 'num_trials' in workload_config else 5


    t0 = time.time()

    print("The paramters are {}".format(params))
    # Set all fields using params object




    service = "node-app"
    workload_config["type"] = "todo-app"
    workload_config["frontend"] = ["54.219.186.95:80"]
    masterNode = ["54.67.52.240"]




    dct = {"54.219.186.95": ["node-app", "haproxy"], "54.219.145.85": ["mongo"]}
    service_index_dct = {"node-app": 0, "haproxy": 1, "mongo": 2}

    # params["CPU-QUOTA"] = [40, 40, 40]
    # params["DISK"] = []
    # params["MEMORY"] = 40
    # params["NET"] = 40

    for mr in params:
        if mr != "CPU-QUOTA":
            for machine in dct:
                sum = 0
                for service in dct[machine]:
                   sum += params[mr][service_index_dct[service]]
                if sum > 120:
                    return 1/0

    for ip in dct:
        workload_config["request_generator"] = [ip]
        client = re.get_client(workload_config["request_generator"][0])

        for name in dct[ip]:

            _, containers, _ = client.exec_command("docker ps | grep " + name + " | awk {'print $1'}")
            containers = containers.read().split("\n")
            if len(containers) > 1:
                containers = containers[:-1]

            instances = [(str(workload_config["request_generator"][0]), container) for container in containers]


            for container in containers:
                resource_modifier.set_cpu_quota(client, container, 250000, params["CPU-QUOTA"][service_index_dct[name]])



            for mr in params:
                if mr not in ["CPU-QUOTA", "CPU-CORE"]:
                    temp_mr = MR(name, mr, instances)

                    max_capacity = instance_specs.get_instance_specs(workload_config["machine_type"])[mr]


                    temp = (params[mr][service_index_dct[name]]/ 100.0) * max_capacity

                    resource_modifier.set_mr_provision(temp_mr, temp,
                                                       workload_config, redis_db)



    workload_config["request_generator"] = masterNode

    client = re.get_client(masterNode[0])
    # re.ssh_exec(client, "sudo apt install apache2-utils")
    # re.ssh_exec(client, "curl -O https://raw.githubusercontent.com/TsaiAnson/mean-a/master/Master\%20Node\%20Files/clear_entries.py")

    # re.ssh_exec(client, "curl -O https://raw.githubusercontent.com/TsaiAnson/mean-a/master/Master\%20Node\%20Files/post.json")


    experiment_results = run_experiment.measure_runtime(workload_config, experiment_trials)
    mean_result = filter_policy.mean_list(experiment_results['latency_99'])


    return mean_result












