'''
Research functions solely for the purpose of experimentation and getting results for Eurosys
'''
import argparse
import matplotlib.pyplot as plt
import redis.client

import modify_resources as resource_modifier
import redis_client as tbot_datastore

from instance_specs import *
from poll_cluster_state import *
from stress_analyzer import *
from run_throttlebot import parse_resource_config_file

def reset_resources():
    vm_list = get_actual_vms()
    all_services = get_actual_services()
    all_resources = get_stressable_resources()

    mr_list = get_all_mrs_cluster(vm_list, all_services, all_resources)
    print 'Resetting provisions for {}'.format([mr.to_string() for mr in mr_list])

    for mr in mr_list:
        resource_modifier.reset_mr_provision(mr)

    print 'All MRs reset'

# INCOMPLETE
# Must set preferred performance index
def plot_cumm_mr(redis_db, num_iterations, workload_config, filter_config):
    mr_count = 0
    tbot_metric = workload_config['tbot_metric']
    all_mrs = get_all_mrs(redis_db)

    mr_to_performance = {}

    for exp_index in range(num_iterations):
        current_performance = tbot_datastore.read_summary_redis(redis_db, exp_index)
        # Count the number of MRs considered the filtering process
        # Just doing this manually because Michael be lazy.
	if filter_config['filter_policy'] == 'pipeline':
        mr_to_performance[mr_count] = current_performance
        mr_count += 1
    elif filter_config['filter_policy'] is None:
        mr_count += 0

        # Count number of MRs considered in the standard approach
        for mr in all_mrs:
            metric = tbot_datastore.read_redis_result(redis_db, exp_index, mr, tbot_metric)
            if len(metric) != 0:
                mr_to_performance[mr_count] = current_performance
                mr_count += 1

    # Plot results from mr_to_performance
    get_by_mr_performance_charts(workload_config, num_iterations, mr_to_performance)

# INCOMPLETE
# Plot the results of the by MR performance
def get_by_mr_performance_charts(workload_config, num_iterations, mr_to_performance):
    experiment_type = workload_config['type']

    # Creating general performance chart
    chart_directory = 'results/graphs/mr/{}/'.format(workload_config['type'] + str(time_id))

    plt.plot(*zip(*sorted(mr_to_performance.items())))
    plt.title('{} Performance Over Time'.format(workload_config['type']))
    plt.xlabel('Elapsed Time (seconds)')
    plt.ylabel('Latency_99 (ms)')
    chart_name = '{}{}{}performance.png'.format(chart_directory, num_iterations, experiment_type)
    plt.savefig(chart_name, bbox_inches='tight')
    plt.clf()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config_file", help='Configuration file for Throttlebot execution')
    parser.add_argument("--reset_resources", action="store_true", help="Reset all resource allocation")
    parser.add_argument("--plot_cumm_mr", type=int, default=0, help="Plots the Performance vs cumulative MRs explored")
    args = parser.parse_args()

    sys_config,workload_config,filter_config = parse_config_file(args.config_file)
    
    redis_host = 'localhost'
    redis_db = redis.StrictRedis(host=redis_host, port=6379, db=0)
                                   
    if args.reset_resources:
        reset_resources()
    elif args.plot_cumm_mr != 0:
        print 'Plotting up to {} iterations'.format(args.plot_cumm_mr)
        plot_cumm_mr(redis_db, args.plot_cumm_mr, workload_config, filter_config)
        
