import argparse
import requests
import json
import numpy as np
import datetime
import numpy
import timeit
import re
import csv
import ast
import os
import socket
import ConfigParser
from random import shuffle

from time import sleep

from collection import namedtuple
from stress_analyzer import *
from modify_resources import *
from weighting_conversions import *
from remote_execution import *
from run_experiment import *
from container_information import *
from present_results import *
from run_spark_streaming import *

import redis_client as tbot_datastore

#Amount of time to allow commands to propagate through system
COMMAND_DELAY = 3

# Frontend for all resource modifications
# Given a MR, this function will take the original resource allocation at the current iteration
# To add a stress, it must be added as a function here.
# If the current resource allocation of the MR is equivalent to R
# increment_level = 20 will cause Tbot to update the resource provision to  R - 0.2R
# increment_level = 0 will allow Tbot to effectively reset the resource provisioning to the previous level
def change_MR_provision(mr, current_mr_allocation, iteration_num, increment_level=0):
    for container_id,vm_id in mr.mr_instances:
        ssh_client = get_client(vm_id)
        print 'STRESSING VM_IP {} AND CONTAINER {}'.format(vm_ip, container_id)
        if mr.resource == 'CPU-CORES':
            num_cores = weighting_to_cpu_cores(ssh_client, increment_level)
            throttle_cpu_cores(ssh_client, container_id, num_cores)
        elif mr.resource == 'CPU-QUOTA':
            cpu_throttle_quota = weighting_to_cpu_quota(increment_level)
            #TODO: Period should not be hardcoded to 1 second
            throttle_cpu_quota(ssh_client, container_id, 1000000, cpu_throttle_quota)
        elif mr.resource == 'DISK':
            disk_throttle_rate = weighting_to_disk_access_rate(increment_level)
            throttle_disk(ssh_client, container_id, disk_throttle_rate)
        elif mr.resource == 'NET':
            container_to_network_capacity = get_container_network_capacity(ssh_client, container_id)
            network_reduction_rate = weighting_to_bandwidth(ssh_client, increment_level, container_to_network_capacity)
            throttle_network(ssh_client, container_id, network_reduction_rate)
        else:
            print 'INVALID resource'
            return

### Throttle only a single resource at a time.
def throttle_cpu_quota(ssh_client, container_id, cpu_period, cpu_quota):
    # update_cpu_through_stress(ssh_client, number_of_stress)
    set_cpu_quota(ssh_client, container_id, cpu_period, cpu_quota)

def throttle_cpu_cores(ssh_client, container_id, cores):
    set_cpu_cores(ssh_client, container_id, cores)

def throttle_disk(ssh_client, container_id, disk_rate):
    print 'Disk Throttle Rate: {}'.format(disk_rate)
    return change_container_blkio(ssh_client, container_id, disk_rate)
    # return create_dummy_disk_eater(ssh_client, disk_rate)

# network_bandwidth is a map from interface->bandwidth
def throttle_network(ssh_client, container_id, network_bandwidth):
    print 'Network Reduction Rate: {}'.format(network_bandwidth)
    set_egress_network_bandwidth(ssh_client, container_id, network_bandwidth)

def stop_throttle_cpu(ssh_client, container_id, cores):
    print 'RESETTING CPU THROTTLING'
    if cores:
        reset_cpu_cores(ssh_client, container_id)
    else:
        reset_cpu_quota(ssh_client, container_id)

def stop_throttle_network(ssh_client, container_id):
    print 'RESETTING NETWORK THROTTLING'
    # reset_egress_network_bandwidth(ssh_client, container_id)
    container_to_network_capacity = get_container_network_capacity(ssh_client, container_id)
    network_bandwith = weighting_to_bandwidth(ssh_client, 0, container_to_network_capacity)
    throttle_network(ssh_client, container_id, network_bandwith)

def stop_throttle_disk(ssh_client, container_id):
    print 'RESETTING DISK THROTTLING'
    change_container_blkio(ssh_client, container_id, 0)
    # remove_dummy_disk_eater(ssh_client, num_fail)

# One-time initialization of Throttlebot Tools
def initialize_experiment(redis_host='localhost'):
    # Initializing Redis DB
    redis_db = redis.StrictRedis(host=redis_host, port=6379, db=0)

def run(system_config, workload_config, cluster_config):
    redis_db = system_config['redis_host']
    baseline_trials = system_config['baseline_trials']
    experiment_trials = system_config['trials']
    increments = system_config['increments']
    preferred_performance_metric = workload_config['tbot_metric']
    
    initialize_experiment(redis_db)
    set_all_resources(cluster_config)
    
    experiment_count = 0
    
    while experiment_count < 3:
        # Run the baseline experiment
        baseline_results = measure_baseline(workload_config, baseline_trials, experiment_count)

        #Get a list of tuples (named tuples) to stress
        mr_to_stress = get_container_ids(ip_addresses)
        for mr in mr_to_stress:
            increment_to_performance = {}
            current_mr_allocation = get_MR_provision(redis_db, mr)
            for increment_level in increments:
                change_MR_provision(mr, current_mr_allocation, experiment_count, increment_level)
                experiment_results = measure_runtime(workload_config, experiment_trials)

                #Remove the effects of the re-provisioning
                change_MR_provision(mr, current_mr_allocation, experiment_count, 0)
                increment_to_performance[increment_level] = experiment_results

            # Write the results of the iteration to Redis
            write_redis_results(redis_db, increment_to_performance, mr, experiment_count, preferred_performance_metric)

        #Recover the results of the experiment from Redis
        mimr = get_mimr(redis_db, experiment_iteration_count)
        
        # Write a summary of the experiment's iterations to Redis
        write_summary_redis(redis_db, experiment_iteration_count, mimr, performance_gain) 

        # TODO: Handle False Positive
        # TODO: Compare against performance condition -- for now only do some number of experiments 

# Run baseline
def measure_baseline(workload_config, baseline_trials=10, experiment_num)
    baseline_runtime_array = measure_runtime(None, workload_config, baseline_trials)
    return baseline_runtime_array

# Parses the configuration parameters for both Throttlebot and the workload that Throttlebot is running
def parse_config_file(config_file):
    sys_config = {}
    workload_config = {}
    
    config = ConfigParser.RawConfigParser()
    config.read(config_file)

    #Configuration Parameters relating to Throttlebot
    sys_config['baseline_trials'] = config.getint('Basic', 'trials')
    sys_config['trials'] = config.getint('Basic', 'trials')
    sys_config['increments'] = config.get('Basic', 'increments').split(',')
    sys_config['stress_these_resources'] = config.get('Basic', 'stress_these_resources').split(',')
    sys_config['stress_these_services'] = config.get('Basic', 'stress_these_services').split(',')
    sys_config['redis_host'] = config.get('Basic', 'redis_host')
    sys_config['stress_policy'] = config.get('Basic', 'stress_policy')
        
    #Configuration Parameters relating to workload
    workload_config['type'] = config.get('Workload', 'type')
    workload_config['request_generator'] = config.get('Workload', 'request_generator').split(',')
    workload_config['frontend'] = config.get('Workload', 'frontend')
    workload_config['tbot_metric'] = config.get('Workload', 'tbot_metric')
    workload_config['performance_target'] = config.get('Workload', 'performance_target')

    #Additional experiment-specific arguments
    additional_args_dict = {}
    workload_args = config.get('Workload', 'additional_args').split(',')
    workload_arg_vals = config.get('Workload', 'additional_arg_values').split(',')
    assert len(workload_args) == len(workload_arg_vals)
    for arg_index in range(len(workload_args)):
        additional_args_dict[workload_args[arg_index]] = workload_arg_vals[arg_index]
    workload_config['additional_args'] = additional_args_dict
    return sys_config, workload_config

def validate_configs(sys_config, workload_config):
    #Validate Address related configuration arguments
    validate_ip([sys_config['redis_host']])
    validate_ip(workload_config['frontend'])
    validate_ip(workload_config['request_generator'])

#Possibly will need to be changed as we start using hostnames in Quilt
def validate_ip(ip_addresses):
    for ip in ip_addresses:
        try:
            socket.inet_aton(ip)
        except:
            print 'The IP Address is Invalid'.format(ip)
            exit()

'''
Experiment arguements takes a list of arguments for the type of experiments
Examples:
"REST": Node TODO App: [public_vm_ip]
"spark-ml-matrix": Spark ml-matrix: [public_vm_ip, private_vm_ip]
"nginx-single": Single unreplicated nginx serving up static pages
'''
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("config_file", help="Configuration File for Throttlebot Execution")
    parser.add_argument("default_resource_config", help='Default Resource Allocation for Throttlebot')
    args = parser.parse_args()
    sys_config, workload_config = parse_config_file(args.config_file)
    resource_allocation = set_default_configuration(args.default_resource_config)
                             
    run_experiment(sys_config, workload_config, resource_allocation)


