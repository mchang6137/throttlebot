import argparse
import csv
import ConfigParser
import time
import numpy as np

import redis.client
import os
currentDirectory = os.getcwd()
os.chdir("../..")
import modify_resources as resource_modifier
import run_experiment
import filter_policy, instance_specs

os.chdir(currentDirectory)

parser = argparse.ArgumentParser()
parser.add_argument("--spearmint_config", help="Spearmint")
args = parser.parse_args()


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
    with open("workload_config") as f:
        for line in f:
           (key, val) = line.split()
           d[int(key)] = val
    return d

workload_config = load_config()

past_results = {}

def main(job_id, params):

    return explore_spearmint(workload_config, params)




def explore_spearmint(workload_config, params):


    param_list = []
    for mr in sorted(params.iterkeys()):
        params[mr] = round(params[mr])
        param_list.add(params[mr])

    if tuple(param_list) in past_results:
        return past_results[tuple(param_list)]





    redis_db = redis.StrictRedis(host='0.0.0.0', port=6379, db=0)
    experiment_trials = workload_config['num_trials']


    t0 = time.time()

    # Set all fields using params object




    for mr in params:
        max_capacity = instance_specs.get_instance_specs("m4.large")[mr]
        params[mr] = (params[mr]/ 100.0) * max_capacity

        resource_modifier.set_mr_provision(mr, params[mr],
                                           workload_config, redis_db)




    experiment_results = run_experiment.measure_runtime(workload_config, experiment_trials)
    preferred_results = experiment_results['success']
    mean_result = filter_policy.mean_list(preferred_results)

    past_results[tuple(param_list)] = mean_result


    return mean_result












