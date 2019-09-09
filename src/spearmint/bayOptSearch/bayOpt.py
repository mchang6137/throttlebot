import argparse
import csv
import ConfigParser
import time
import numpy as np

import redis.client
import src.modify_resources as resource_modifier

parser = argparse.ArgumentParser()
parser.add_argument("--spearmint_config", help="Spearmint")
args = parser.parse_args()


def parse_config_file():
    workload_config['type'] = 'spark-ml-matrix'
    workload_config['request_generator'] = [1]  # request generator
    workload_config['additional_args'] = {'container_id': 'blah'}
    workload_config['num_trials'] = 5
    return workload_config


workload_config = parse_config_file()




def main(job_id, params):

    return explore_spearmint(workload_config, params)


def explore_spearmint(workload_config, params):
    redis_db = redis.StrictRedis(host='0.0.0.0', port=6379, db=0)
    experiment_trials = workload_config['num_trials']

    #These are placeholders
    ssh_client = get_client()
    container_id = workload_config["vm"]

    t0 = time.time()

    # Set all fields using params object
    resource_modifier.set_cpu_quota(ssh_client, container_id, cpu_period, params.cpu_quota)
    resource_modifier.set_cpu_cores(ssh_client, container_id, params.cpu_cores)



    experiment_results = measure_runtime(workload_config, experiment_trials)
    preferred_results = experiment_results['success']
    mean_result = mean_list(preferred_results)

    with open('spearmint_results.csv', 'w') as csvfile:
        fieldnames = []
        for mr in spearmint_allocation:
            mr_string = mr.to_string_csv()
            fieldnames.append(mr_string)
        fieldnames.append('perf')
        fieldnames.append('time_elapsed')

        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writerheader()
        result_dict = {}
        for mr in spearmint_allocation:
            result_dict[mr.to_string_csv()] = spearmint_allocation[mr]
        result_dict['perf'] = mean_result
        result_dict['time_elapsed'] = time.time() - t0
        writer.writerow(result_dict)

    return mean_result












