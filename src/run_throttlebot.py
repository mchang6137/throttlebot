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
from cluster_information import *

from stress_analyzer import MR

import redis_client as tbot_datastore
import redis_resource as resource_datastore

'''
Functions that enable stressing resources and determining how much to stress
Stresses implemented in: modify_resources.py
'''

# Sets the resource provision for all containers in a service
def set_mr_provision(mr, new_mr_allocation):
    for vm_ip,container_id in mr.mr_instances:
        ssh_client = get_client(vm_ip)
        print 'STRESSING VM_IP {} AND CONTAINER {}'.format(vm_ip, container_id)
        if mr.resource == 'CPU-CORE':
            set_cpu_cores(ssh_client, container_id, new_mr_allocation)
        elif mr.resource == 'CPU-QUOTA':
            #TODO: Period should not be hardcoded to 1 second
            set_cpu_quota(ssh_client, container_id, 1000000, new_mr_allocation)
        elif mr.resource == 'DISK':
            change_container_blkio(ssh_client, container_id, new_mr_allocation)
        elif mr.resource == 'NET':
            set_egress_network_bandwidth(ssh_client, container_id, new_mr_allocation)
        else:
            print 'INVALID resource'
            return
        
# Converts a change in resource provisioning to raw change
# current_mr_allocation is dict for a MR from its resource to its provision
# Example: 20% -> 24 Gbps
def convert_percent_to_raw(mr, current_service_allocation, weight_change=0):
    if mr.resource == 'CPU-CORE':
        return weighting_to_cpu_cores(weight_change, current_mr_allocation['CPU-CORE'])
    elif mr.resource == 'CPU-QUOTA':
        return weighting_to_cpu_quota(weight_change, current_mr_allocation['CPU-QUOTA'])
    elif mr.resource == 'DISK':
        return  weighting_to_blkio(weight_change, current_mr_allocation['DISK'])
    elif mr.resource == 'NET':
        return weighting_to_net_bandwidth(weight_change, current_mr_allocation)
    else:
        print 'INVALID resource'
        exit()

'''
Initialization: 
Set Default resource allocations and initialize Redis to reflect those initial allocations
'''

# Collect real information about the cluster and write to redis
# ALL Information (regardless of user inputs are collected in this step)
def init_service_placement_r(redis_db, default_mr_configuration):
    services_seen = []
    for mr in default_mr_configuration:
        if mr.service_name not in services_seen:
            tbot_datastore.write_service_locations(redis_db, mr.service_name, mr.instances)
            services_seen.append(mr.service_name)
        else:
            continue

# Set the current resource configurations within the actual containers
# Data points in resource_config are expressed in percentage change
def init_resource_config(redis_db, default_mr_config, machine_type):
    print 'Initializing the Resource Configurations in the containers'
    instance_specs = get_instance_specs(machine_type)
    
    for mr in default_mr_config:
        weight_change = resource_config[mr]
        new_resource_provision = convert_percent_to_raw(mr, instance_specs, weight_change)
        # Enact the change in resource provisioning
        set_mr_provision(mr, new_resource_provision)

        # Reflect the change in Redis
        resource_datastore.write_mr_alloc(redis_db, mr, new_resource_provision)
        update_machine_consumption(redis_db, mr, new_resource_provision, 0)

# Initializes the maximum capacity and current consumption of Quilt
def init_cluster_capacities_r(redis_db, machine_type, quilt_overhead):
    print 'Initializing the per machine capacities'
    resource_alloc = get_instance_specs(machine_type)
    quilt_usage = {}

    # Leave some resources available for Quilt containers to run (OVS, etc.)
    # This is dictated by quilt overhead
    for resource in resource_alloc:
        max_cap = resource_alloc[resource]
        quilt_usage[resource] = ((quilt_overhead)/100.0) * max_cap
    
    all_vms = get_actual_vms()

    for vm_ip in all_vms:
        write_machine_consumption(redis_db, vm_ip, quilt_usage)
        write_machine_capacity(redis_db, vm_ip, resource_alloc)

''' 
Tools that are used for experimental purposes in Throttlebot 
'''

# Determine Amount to improve a MIMR
def improve_mr_by(redis_db, mimr, weight_stressed):
    #Simple heuristic currently: Just improve by amount it was improved
    return (weight_stressed * -1)

# Run baseline
def measure_baseline(workload_config, baseline_trials=10, experiment_num)
    baseline_runtime_array = measure_runtime(None, workload_config, baseline_trials)
    return baseline_runtime_array

# Checks if the current system can support improvements in a particular MR
# Improvement amount is the raw amount a resource is being improved by
# Always leave 10% of system resources available for Quilt
def check_improve_mr_viability(redis_db, mr, improvement_amount):
    print 'Checking MR viability'

    # Check if available space on machines being tested
    for instance in mr.instances:
        vm_ip,container_id = instance
        machine_consumption = read_machine_consumption(redis_db, vm_ip)
        machine_capacity = read_machine_capacity(redis_db, vm_ip)

        if machine_consumption + improvement_amount > machine_capacity:
            return False
    return True

# Update the resource consumption of a machine after an MIMR has been improved
def update_machine_consumption(redis_db, mr, new_alloc, old_alloc):
    for instance in mr.instances:
        vm_ip,container_id = instance
        prior_consumption = read_machine_consumption(redis_db, vm_ip)
        new_consumption = prior_consumption + new_alloc - old_alloc
        resource_datastore.write_machine_consumption(redis_db, vm_ip,  new_consumption)

# Updates the MR configuration from resource datastore
def update_mr_config(redis_db, mr_in_play):
    updated_configuration = {}
    for mr in default_mr_config:
        updated_configuration[mr] = resource_datastore.read_mr_alloc(redis_db, mr)
    return updated_configuration

'''
Primary Run method that is called from the main
system_config: Throttlebot related General parameters in a dict
workload_config: Parameters about the workload in a dict
default_mr_config: Filtered MRs that should be stress along with their default allocation
'''

def run(system_config, workload_config, default_mr_config):
    redis_host = system_config['redis_host']
    baseline_trials = system_config['baseline_trials']
    experiment_trials = system_config['trials']
    stress_weights = system_config['stress_weights']
    stress_policy = system_config['stress_policy']
    resource_to_stress = system_config['stress_these_resources']
    service_to_stress = system_config['stress_these_services']
    vm_to_stress = system_config['stress_these_machines']
    machine_type = system_config['machine_type']
    quilt_overhead = system_config['quilt_overhead']
    
    preferred_performance_metric = workload_config['tbot_metric']
    optimize_for_lowest = workload_config['optimize_for_lowest']

    redis_db = redis.StrictRedis(host=redis_host, port=6379, db=0)

    # Initialize Redis and Cluster based on the default resource configuration
    init_cluster_capacities_r(redis_db, quilt_overhead)
    init_service_placement_r(redis_db, default_mr_config)
    init_resource_config(redis_db, defaut_mr_config, machine_type)
    
    # Run the baseline experiment
    baseline_results = measure_baseline(workload_config, baseline_trials, experiment_count)
    experiment_count = 0

    # Initialize the current configurations
    # Invariant: MR are the same between iterations
    current_mr_config = update_mr_config(redis_db, default_mr_config)

    while experiment_count < 3:
        # Get a list of MRs to stress in the form of a list of MRs
        mr_to_stress = generate_mr_from_policy(stress_policy, current_mr_config)
        current_mr_allocation = get_MR_provision(redis_db, mr)
        for mr in mr_to_stress:
            increment_to_performance = {}
            for stress_weight in stress_weights:
                new_alloc = convert_percent_to_raw(mr, current_mr_allocation, stress_weight)
                set_mr_provision(mr, new_alloc)
                experiment_results = measure_runtime(workload_config, experiment_trials)

                #Write results of experiment to Redis
                mean_result = float(sum(experiment_results[preferred_performance_metric])) /
                              len(experiment_results[preferred_performance_metric])
                tbot_datastore.write_redis_ranking(redis_db, experiment_count, preferred_performance_metric, mean_result, mr, stress_weight)
                
                # Remove the effect of the resource stressing
                new_alloc = convert_percent_to_raw(mr, current_mr_allocation, 0)
                increment_to_performance[stress_weight] = experiment_results

            # Write the results of the iteration to Redis
            tbot_datastore.write_redis_results(redis_db, increment_to_performance, mr, experiment_count, preferred_performance_metric)
        
        # Recover the results of the experiment from Redis
        max_stress_weight = min(stress_weights)
        mimr_list = tbot_datastore.get_top_n_mimr(redis_db, experiment_iteration_count, preferred_performance_metric, max_stress_weight, 
                                   get_lowest=optimize_for_lowest, 10)
        
        # Try all the MIMRs in the list until a viable improvement is determined
        # Improvement Amount 
        for mr in mimr_list:
            improvement_percent = improve_mr_by(redis_db, mr)
            new_alloc = convert_percent_to_raw(mr, current_mr_allocation, improvement_percent)
            if check_improve_mr_viability(mr, new_alloc):
                set_mr_provision(mr, new_alloc)
                print 'Improvement Calculated: MR {} improved by {}'.format(mr.to_string(), new_alloc)
                old_alloc = resource_datastore.read_mr_alloc(redis_db, mr)
                resource_datastore.write_mr_alloc(redis_db, mr, new_alloc)
                update_mr_consumption(redis_db, mr, new_alloc, old_alloc)
                current_mr_config = update_mr_config(redis_db, current_mr_config)
                break
            else:
                print 'Improvement Attempted by not viable: MR {} improved by {}'.format(mr.to_string(), new_alloc)

        #Compare against the baseline at the beginning of the program
        improved_performance = measure_runtime(workload_config, baseline_trials, experiment_count)
        performance_improvement = improved_performance - baseline_results
        
        # Write a summary of the experiment's iterations to Redis
        tbot_datastore.write_summary_redis(redis_db, experiment_iteration_count, mimr, performance_improvement) 
        baseline_performance = improved_performance

        results = tbot_datastore.read_summary_redis(redis_db, experiment_iteration_count)
        print 'Results from iteration {} are {}'.format(experiment_iteration_count, results)
        
        # TODO: Handle False Positive
        # TODO: Compare against performance condition -- for now only do some number of experiments

    print '{} experiments completed'.format(experiment_iteration_count)
    print 'New resource configuration = {}'.format(current_mr_config)

'''
Functions to parse configuration files
Parses Throttlebot config file and the Resource Allocation Configuration File
'''

# Parses the configuration parameters for both Throttlebot and the workload that Throttlebot is running
def parse_config_file(config_file):
    sys_config = {}
    workload_config = {}
    
    config = ConfigParser.RawConfigParser()
    config.read(config_file)

    #Configuration Parameters relating to Throttlebot
    sys_config['baseline_trials'] = config.getint('Basic', 'trials')
    sys_config['trials'] = config.getint('Basic', 'trials')
    sys_config['stress_weight'] = config.get('Basic', 'stress_weight').split(',')
    sys_config['stress_these_resources'] = config.get('Basic', 'stress_these_resources').split(',')
    sys_config['stress_these_services'] = config.get('Basic', 'stress_these_services').split(',')
    sys_config['stress_these_machines'] = config.get('Basic', 'stress_these_machines').split(',')
    sys_config['redis_host'] = config.get('Basic', 'redis_host')
    sys_config['stress_policy'] = config.get('Basic', 'stress_policy')
    sys_config['machine_type'] = config.get('Basic', 'machine_type')
    sys_config['quilt_overhead'] = config.get('Basic', 'quilt_overhead')
        
    #Configuration Parameters relating to workload
    workload_config['type'] = config.get('Workload', 'type')
    workload_config['request_generator'] = config.get('Workload', 'request_generator').split(',')
    workload_config['frontend'] = config.get('Workload', 'frontend')
    workload_config['tbot_metric'] = config.get('Workload', 'tbot_metric')
    workload_config['tbot_metric_optimal'] = config.getboolean('Workload', 'optimize_for_lowest')
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

# Parse a default resource configuration
# Gathers the information from directly querying the machines on the cluster
# This should be ONLY TIME the machines are queried directly -- remaining calls
# should be conducted from Redis
#
# Returns a mapping of a MR to its current resource allocation (percentage amount)
def parse_resource_conf_file(resource_config):
    vm_list = get_actual_vms()
    all_services = get_actual_services()
    all_resources = get_stressable_resources()
    
    mr_allocation = {}
    
    # Empty Config means that we should default resource allocation to only use
    # half of the total resource capacity on the machine
    if resource_config is None:
        service_to_deployment = get_service_placements(vm_list)
        vm_to_service = get_vm_to_service(vm_list)
        instance_specs = get_instance_specs(instance_type)

        # DEFAULT_ALLOCATION sets the initial configuration
        # Ensure that we will not violate resource provisioning in the machine
        # Assign resources equally to services without exceeding machine resource limitations
        max_num_services = 0
        for vm in vm_to_service:
            if len(vm_to_service[vm]) > max_num_services:
                max_num_services = len(vm_to_service[vm])
        default_alloc_percentage = 50.0 / max_num_services
        mr_list = get_all_mrs(vm_list, all_services, all_resources)
        for mr in mr_list:
            mr_allocation[mr] = default_alloc_percentage
    else:
        # Manual Configuration possible here, to be implemented
        print 'Placeholder for a way to configure the resources'

    return mr_allocation

# Throttlebot allows regex * to represent ALL
def resolve_config_wildcards(sys_config, workload_config):
    if sys_config['stress_these_services'][0] == '*':
        sys_config['stress_these_services'] = get_actual_vms()
    if sys_config['stress_these_machines'] == '*':
        sys_config['stress_these_machines'] = get_actual_services()

def validate_configs(sys_config, workload_config):
    #Validate Address related configuration arguments
    validate_ip([sys_config['redis_host']])
    validate_ip(workload_config['frontend'])
    validate_ip(workload_config['request_generator'])

    for resource in sys_config['stress_these_resources'] :
        if resource == 'CPU-CORE' or
                       'CPU-QUOTA' or
                       'DISK'      or
                       'NET'       or
                       '*':
            continue
        else:
            print 'Cannot stress a specified resource: {}'.format(resource)

#Possibly will need to be changed as we start using hostnames in Quilt
def validate_ip(ip_addresses):
    for ip in ip_addresses:
        try:
            socket.inet_aton(ip)
        except:
            print 'The IP Address is Invalid'.format(ip)
            exit()

# Filter out resources, services, and machines that shouldn't be stressed on this iteration
# Automatically Filter out Quilt-specific modules
def filter_mr(mr_allocation, acceptable_resources, acceptable_services, acceptable_machines):
    for mr in mr_allocation:
        if mr.service_name in get_quilt_services():
            del mr_allocation[mr]
        if '*' not in acceptable_services and mr.service_name not in acceptable_services:
            del mr_allocation[mr]
        # Cannot have both CPU and Quota Stressing
        # Default to reducing the number of cores
        if '*' in acceptable_resources and mr.resource == 'CPU-QUOTA':
            del mr_allocation[mr]
        elif '*' not in acceptable_resources and mr.service_name not in acceptable_resources:
            del mr_allocation[mr]
        # Temporarily ignoring acceptable_machines since it might be unnecessary
        # and it is hard to solve...
    return mr_allocation

'''
Experiment arguements takes a list of arguments for the type of experiments
Examples:
"REST": Node TODO App: [public_vm_ip]
"spark-ml-matrix": Spark ml-matrix: [public_vm_ip, private_vm_ip]
"nginx-single": Single unreplicated nginx serving up static pages
'''
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config_file", help="Configuration File for Throttlebot Execution")
    parser.add_argument("--resource_config", help='Default Resource Allocation for Throttlebot')
    args = parser.parse_args()
    
    sys_config, workload_config = parse_config_file(args.config_file)
    mr_allocation = parse_resource_config_file(args.default_resource_config)

    # While stress policies can further filter MRs, the first filter is applied here
    # mr_allocation should include only the MRs that are included
    mr_allocation = filter_mr(mr_allocation,
                              sys_config['stress_these_resources'],
                              sys_config['stress_these_services'],
                              sys_config['stress_these_machines'])
                             
    run(sys_config, workload_config, mr_allocation)

