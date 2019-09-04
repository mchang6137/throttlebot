import argparse
import csv
import ConfigParser
import time

import redis.client
import modify_resources as resource_modifier

def explore_spearmint(workload_config):
    redis_db = redis.StrictRedis(host='0.0.0.0', port=6379, db=0)
    experiment_trials = worklaod_config['num_trials']

    t0 = time.time()
    while True:
        spearmint_allocation = call_spearmint()
        for mr in spearmint_allocation:
            resource_modifier.set_mr_provision(mr, spearmint_allocation[mr],
                                           workload_config, redis_db)
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

 def parse_config_file():
    workload_config['type'] = 'spark-ml-matrix'
    workload_config['request_generator'] = [1] #request generator 
    workload_config['additional_args'] = {'container_id': 'blah'}
    workload_config['num_trials'] = 5
    return workload_config

# Select next configuration setting to test
# Currently a dummy function
def call_spearmint():
    print 'Calling Spearmint'
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--spearmint_config", help="Spearmint")
    args = parser.parse_args()

    workload_config = parse_config_file()
    explore_spearmint(workload_config)
    

    
