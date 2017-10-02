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

from collections import namedtuple

from stress_analyzer import *
from weighting_conversions import *
from remote_execution import *
from run_experiment import *
from container_information import *
from cluster_information import *
from filter_policy import *
from mr	import MR

import redis.client
import redis_client as tbot_datastore
import redis_resource as resource_datastore
import modify_resources as resource_modifier

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
        new_resource_provision = default_mr_config[mr]
        if check_improve_mr_viability(redis_db, mr, new_resource_provision) is False:
            print 'Initial Resource provisioning for {} is too much. Exiting...'.format(mr.to_string())
            exit()
            
        # Enact the change in resource provisioning
        resource_modifier.set_mr_provision(mr, new_resource_provision)

        # Reflect the change in Redis
        resource_datastore.write_mr_alloc(redis_db, mr, new_resource_provision)
        update_machine_consumption(redis_db, mr, new_resource_provision, 0)

# Initializes the maximum capacity and current consumption of Quilt
def init_cluster_capacities_r(redis_db, machine_type, quilt_overhead):
    print 'Initializing the per machine capacities'
    resource_alloc = get_instance_specs(machine_type)
    quilt_usage = {}

    # Leave some resources available for Quilt containers to run (OVS, etc.)
     # This is dictated by quilt overheads
    for resource in resource_alloc:
        max_cap = resource_alloc[resource]
        quilt_usage[resource] = ((quilt_overhead)/100.0) * max_cap
    
    all_vms = get_actual_vms()

    for vm_ip in all_vms:
        resource_datastore.write_machine_consumption(redis_db, vm_ip, quilt_usage)
        resource_datastore.write_machine_capacity(redis_db, vm_ip, resource_alloc)

''' 
Tools that are used for experimental purposes in Throttlebot 
'''

# Determine Amount to improve a MIMR
def improve_mr_by(redis_db, mimr, weight_stressed):
    #Simple heuristic currently: Just improve by amount it was improved
    return (weight_stressed * -1)

# Run baseline
def measure_baseline(workload_config, baseline_trials=10):
    baseline_runtime_array = measure_runtime(workload_config, baseline_trials)
    return baseline_runtime_array

# Checks if the current system can support improvements in a particular MR
# Improvement amount is the raw amount a resource is being improved by
# Always leave 10% of system resources available for Quilt
def check_improve_mr_viability(redis_db, mr, improvement_amount):
    print 'Checking MR viability'

    # Check if available space on machines being tested
    for instance in mr.instances:
        vm_ip,container_id = instance
        machine_consumption = resource_datastore.read_machine_consumption(redis_db, vm_ip)
        machine_capacity = resource_datastore.read_machine_capacity(redis_db, vm_ip)

        if machine_consumption[mr.resource] + improvement_amount > machine_capacity[mr.resource]:
            return False
    return True

# Update the resource consumption of a machine after an MIMR has been improved
# Assumes that the new allocation of resources is valid 
def update_machine_consumption(redis_db, mr, new_alloc, old_alloc):
    for instance in mr.instances:
        vm_ip,container_id = instance
        prior_consumption = resource_datastore.read_machine_consumption(redis_db, vm_ip)
        new_consumption = float(prior_consumption[mr.resource]) + new_alloc - old_alloc

        utilization_dict = {}
        utilization_dict[mr.resource] = new_consumption
        resource_datastore.write_machine_consumption(redis_db, vm_ip,  utilization_dict)

# Updates the MR configuration from resource datastore
def update_mr_config(redis_db, mr_in_play):
    updated_configuration = {}
    for mr in mr_in_play:
        updated_configuration[mr] = resource_datastore.read_mr_alloc(redis_db, mr)
    return updated_configuration

# Prints all improvements attempted by Throttlebot
def print_all_steps(redis_db, total_experiments):
    print 'Steps towards improving performance'
    net_improvement = 0
    for experiment_count in range(total_experiments):
        mimr,action_taken,perf_improvement = tbot_datastore.read_summary_redis(redis_db, experiment_count)
        print 'Iteration {}, Mimr = {}, New allocation = {}, Performance Improvement = {}'.format(experiment_count, mimr, action_taken, perf_improvement)
        net_improvement += float(perf_improvement)
    print 'Net Improvement: {}'.format(net_improvement)

# Writes a CSV that can be re-fed into Throttlebot as a configuration
def print_csv_configuration(final_configuration, output_csv='tuned_config.csv'):
    with open(output_csv, 'w') as csvfile:
        fieldnames = ['SERVICE', 'RESOURCE', 'AMOUNT', 'REPR']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for mr in final_configuration:
            result_dict = {}
            result_dict['SERVICE'] = mr.service_name
            result_dict['RESOURCE'] = mr.resource
            result_dict['AMOUNT'] = final_configuration[mr]
            result_dict['REPR'] = 'RAW'
            writer.writerow(result_dict)
    
'''
Primary Run method that is called from the main
system_config: Throttlebot related General parameters in a dict
workload_config: Parameters about the workload in a dict
default_mr_config: Filtered MRs that should be stress along with their default allocation
'''

def run(system_config, workload_config, filter_config, default_mr_config):
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
    redis_db.flushall()

    print '\n' * 2
    print '*' * 20
    print 'INFO: INITIALIZING RESOURCE CONFIG'
    # Initialize Redis and Cluster based on the default resource configuration
    init_cluster_capacities_r(redis_db, machine_type, quilt_overhead)
    init_service_placement_r(redis_db, default_mr_config)
    init_resource_config(redis_db, default_mr_config, machine_type)
    
    print '*' * 20
    print 'INFO: INSTALLING DEPENDENCIES'
    install_dependencies(workload_config)
    
    print '*' * 20
    print 'INFO: RUNNING BASELINE'
    # Run the baseline experiment
    experiment_count = 0
    baseline_performance = measure_baseline(workload_config, baseline_trials)
    print '*' * 20
    print '\n' * 2

    # Initialize the current configurations
    # Invariant: MR are the same between iterations
    current_mr_config = resource_datastore.read_all_mr_alloc(redis_db)

    #Initialize the working set of MRs to all the MRs
    mr_working_set = resource_datastore.get_all_mrs(redis_db)
    resource_datastore.write_mr_working_set(redis_db, mr_working_set, 0)

    # Initialize time for data charts
    time_id = str(datetime.datetime.now())

    while experiment_count < 5:
        # Get a list of MRs to stress in the form of a list of MRs
        mr_to_stress = apply_filtering_policy(redis_db,
                                              mr_working_set,
                                              experiment_count,
                                              workload_config,
                                              filter_config)
        
        for mr in mr_to_stress:
            print '\n' * 2
            print '*' * 20
            print 'Current MR is {}'.format(mr.to_string())
            increment_to_performance = {}
            current_mr_allocation = resource_datastore.read_mr_alloc(redis_db, mr)
            print 'Current MR allocation is {}'.format(current_mr_allocation)
            for stress_weight in stress_weights:
                new_alloc = convert_percent_to_raw(mr, current_mr_allocation, stress_weight)
                resource_modifier.set_mr_provision(mr, new_alloc)
                experiment_results = measure_runtime(workload_config, experiment_trials)

                #Write results of experiment to Redis
                mean_result = float(sum(experiment_results[preferred_performance_metric])) / len(experiment_results[preferred_performance_metric])
                tbot_datastore.write_redis_ranking(redis_db, experiment_count, preferred_performance_metric, mean_result, mr, stress_weight)

                # Remove the effect of the resource stressing
                new_alloc = convert_percent_to_raw(mr, current_mr_allocation, 0)
                resource_modifier.set_mr_provision(mr, new_alloc)
                increment_to_performance[stress_weight] = experiment_results

            # Write the results of the iteration to Redis
            tbot_datastore.write_redis_results(redis_db, mr, increment_to_performance, experiment_count, preferred_performance_metric)
            print '*' * 20
            print '\n' * 2

        # Save data in chart form
        tbot_datastore.get_summary_mimr_charts(redis_db, workload_config, baseline_performance, mr_working_set,
                                               experiment_count, stress_weights, preferred_performance_metric, time_id)

        # Recover the results of the experiment from Redis
        max_stress_weight = min(stress_weights)
        mimr_list = tbot_datastore.get_top_n_mimr(redis_db, experiment_count, preferred_performance_metric, max_stress_weight, 
                                   optimize_for_lowest=optimize_for_lowest, num_results_returned=10)
        
        # Try all the MIMRs in the list until a viable improvement is determined
        # Improvement Amount
        mimr = None
        action_taken = 0
        print 'The MR improvement is {}'.format(max_stress_weight)
        for mr_score in mimr_list:
            mr, score = mr_score
            improvement_percent = improve_mr_by(redis_db, mr, max_stress_weight)
            current_mr_allocation = resource_datastore.read_mr_alloc(redis_db, mr)
            new_alloc = convert_percent_to_raw(mr, current_mr_allocation, improvement_percent)
            improvement_amount = new_alloc - current_mr_allocation
            action_taken = improvement_amount
            if check_improve_mr_viability(redis_db, mr, improvement_amount):
                resource_modifier.set_mr_provision(mr, new_alloc)
                print 'Improvement Calculated: MR {} increase from {} to {}'.format(mr.to_string(), current_mr_allocation, new_alloc)
                old_alloc = resource_datastore.read_mr_alloc(redis_db, mr)
                resource_datastore.write_mr_alloc(redis_db, mr, new_alloc)
                update_machine_consumption(redis_db, mr, new_alloc, old_alloc)
                current_mr_config = update_mr_config(redis_db, current_mr_config)
                mimr = mr
                break
            else:
                print 'Improvement Calculated: MR {} failed to improve from {} to {}'.format(mr.to_string(), current_mr_allocation, new_alloc)
                
        if mimr is None:
            print 'No viable improvement found'
            break

        #Compare against the baseline at the beginning of the program
        improved_performance = measure_runtime(workload_config, baseline_trials)
        print improved_performance
        improved_mean = sum(improved_performance[preferred_performance_metric]) / float(len(improved_performance[preferred_performance_metric]))
        baseline_mean = sum(baseline_performance[preferred_performance_metric]) / float(len(baseline_performance[preferred_performance_metric]))                                                                           
        performance_improvement = improved_mean - baseline_mean
        
        # Write a summary of the experiment's iterations to Redis
        tbot_datastore.write_summary_redis(redis_db, experiment_count, mimr, performance_improvement, action_taken) 
        baseline_performance = improved_performance

        results = tbot_datastore.read_summary_redis(redis_db, experiment_count)
        print 'Results from iteration {} are {}'.format(experiment_count, results)
        experiment_count += 1
        
        # TODO: Handle False Positive
        # TODO: Compare against performance condition -- for now only do some number of experiments

    print '{} experiments completed'.format(experiment_count)
    print_all_steps(redis_db, experiment_count)
    for mr in current_mr_config:
        print '{} = {}'.format(mr.to_string(), current_mr_config[mr])
        
    print_csv_configuration(current_mr_config)

'''
Functions to parse configuration files
Parses Throttlebot config file and the Resource Allocation Configuration File
'''

# Parses the configuration parameters for both Throttlebot and the workload that Throttlebot is running
def parse_config_file(config_file):
    sys_config = {}
    workload_config = {}
    filter_config = {}
    
    config = ConfigParser.RawConfigParser(allow_no_value=True)
    config.read(config_file)

    #Configuration Parameters relating to Throttlebot
    sys_config['baseline_trials'] = config.getint('Basic', 'baseline_trials')
    sys_config['trials'] = config.getint('Basic', 'trials')
    stress_weights = config.get('Basic', 'stress_weights').split(',')
    sys_config['stress_weights'] = [int(x) for x in stress_weights]
    sys_config['stress_these_resources'] = config.get('Basic', 'stress_these_resources').split(',')
    sys_config['stress_these_services'] = config.get('Basic', 'stress_these_services').split(',')
    sys_config['stress_these_machines'] = config.get('Basic', 'stress_these_machines').split(',')
    sys_config['redis_host'] = config.get('Basic', 'redis_host')
    sys_config['stress_policy'] = config.get('Basic', 'stress_policy')
    sys_config['machine_type'] = config.get('Basic', 'machine_type')
    sys_config['quilt_overhead'] = config.getint('Basic', 'quilt_overhead')

    # Configuration parameters relating to the filter step
    filter_config['filter_policy'] = config.get('Filter', 'filter_policy')
    filter_config['stress_amount'] = config.getint('Filter', 'stress_amount')
    filter_config['filter_exp_trials'] = config.getint('Filter', 'filter_exp_trials')
    pipeline_string = config.get('Filter', 'pipeline_services')
    # If filter_policy is none, will set to none
    if filter_config['filter_policy'] == '':
        filter_config['filter_policy'] = None
    # If pipeline_string is none, then each service is individually a pipeline
    if pipeline_string == '':
        filter_config['pipeline_services'] = None
    else:
        pipelines = pipeline_string.split(',')
        pipelines = [pipeline.split('-') for pipeline in pipelines]
        filter_config['pipeline_services'] = pipelines
        
    #Configuration Parameters relating to workload
    workload_config['type'] = config.get('Workload', 'type')
    workload_config['request_generator'] = config.get('Workload', 'request_generator').split(',')
    workload_config['frontend'] = config.get('Workload', 'frontend').split(',')
    workload_config['tbot_metric'] = config.get('Workload', 'tbot_metric')
    workload_config['optimize_for_lowest'] = config.getboolean('Workload', 'optimize_for_lowest')
    workload_config['performance_target'] = config.get('Workload', 'performance_target')
    
    #Additional experiment-specific arguments
    additional_args_dict = {}
    workload_args = config.get('Workload', 'additional_args').split(',')
    workload_arg_vals = config.get('Workload', 'additional_arg_values').split(',')
    assert len(workload_args) == len(workload_arg_vals)
    for arg_index in range(len(workload_args)):
        additional_args_dict[workload_args[arg_index]] = workload_arg_vals[arg_index]
    workload_config['additional_args'] = additional_args_dict
    
    return sys_config, workload_config, filter_config

# Parse a default resource configuration
# Gathers the information from directly querying the machines on the cluster
# This should be ONLY TIME the machines are queried directly -- remaining calls
# should be conducted from Redis
#
# The provisioning may be invalid, this will be checked in a later function
# Returns a mapping of a MR to its current resource allocation (in terms of the raw amount)
def parse_resource_config_file(resource_config_csv, sys_config):
    machine_type = sys_config['machine_type']
    
    vm_list = get_actual_vms()
    service_placements = get_service_placements(vm_list)
    all_services = get_actual_services()
    all_resources = get_stressable_resources()
    
    mr_allocation = {}
    
    # Empty Config means that we should default resource allocation to only use
    # half of the total resource capacity on the machine
    if resource_config_csv is None:
        vm_to_service = get_vm_to_service(vm_list)
        # DEFAULT_ALLOCATION sets the initial configuration
        # Ensure that we will not violate resource provisioning in the machine
        # Assign resources equally to services without exceeding machine resource limitations
        max_num_services = 0
        for vm in vm_to_service:
            if len(vm_to_service[vm]) > max_num_services:
                max_num_services = len(vm_to_service[vm])
        default_alloc_percentage = 50.0 / max_num_services

        mr_list = get_all_mrs_cluster(vm_list, all_services, all_resources)
        for mr in mr_list:
            max_capacity = get_instance_specs(machine_type)[mr.resource]
            default_raw_alloc = (default_alloc_percentage / 100.0) * max_capacity
            mr_allocation[mr] = default_raw_alloc
        print mr_allocation
    else:
        # Manual Configuration Possible
        # Parse a CSV
        # Format of resource allocation: SERVICE,RESOURCE,TYPE,REPR
        mr_list = get_all_mrs_cluster(vm_list, all_services, all_resources)
        with open(resource_config_csv, 'rb') as resource_config:
            reader = csv.DictReader(resource_config)

            for row in reader:
                service_name = row['SERVICE']
                resource = row['RESOURCE']
                amount = float(row['AMOUNT'])
                amount_repr = row['REPR']

                # Convert REPR to RAW AMOUNT
                if amount_repr == 'PERCENT':
                    if amount <= 0 or amount > 100:
                        print 'Error: invalid default percentage. Exiting...'
                        exit()
                    max_capacity = get_instance_specs(machine_type)[resource]
                    amount = (amount / 100.0) * max_capacity

                mr = MR(service_name, resource, service_placements[service_name])
                assert mr in mr_list
                mr_allocation[mr] = amount

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
        if resource in ['CPU-CORE', 'CPU-QUOTA', 'DISK', 'NET', 'MEMORY', '*']:
            continue
        else:
            print 'Cannot stress a specified resource: {}'.format(resource)

#Possibly will need to be changed as we start using hostnames in Quilt
def validate_ip(ip_addresses):
    for ip in ip_addresses:
        try:
            socket.inet_aton(ip)
        except:
            print 'The IP Address {} is Invalid'.format(ip)
            exit()

# Installs dependencies on machines if needed
def install_dependencies(workload_config):
    traffic_machines = workload_config['request_generator']
    if traffic_machines == ['']:
        return
    for traffic_machine in traffic_machines:
        traffic_client = get_client(traffic_machine)
        ssh_exec(traffic_client, 'sudo apt-get install apache2-utils -y')
        close_client(traffic_client)


# Filter out resources, services, and machines that shouldn't be stressed on this iteration
# Automatically Filter out Quilt-specific modules
def filter_mr(mr_allocation, acceptable_resources, acceptable_services, acceptable_machines):
    delete_queue = []
    for mr in mr_allocation:
        if mr.service_name in get_quilt_services():
            delete_queue.append(mr)
        elif '*' not in acceptable_services and mr.service_name not in acceptable_services:
            delete_queue.append(mr)
        # Cannot have both CPU and Quota Stressing
        # Default to using quota
        elif '*' in acceptable_resources and mr.resource == 'CPU-CORE':
            delete_queue.append(mr)
        elif '*' not in acceptable_resources and mr.resource not in acceptable_resources:
            delete_queue.append(mr)
        # Temporarily ignoring acceptable_machines since it might be unnecessary
        # and it is hard to solve...

    for mr in delete_queue:
        print 'Deleting MR: ', mr.to_string()
        del mr_allocation[mr]
    
    return mr_allocation


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config_file", help="Configuration File for Throttlebot Execution")
    parser.add_argument("--resource_config", help='Default Resource Allocation for Throttlebot')
    args = parser.parse_args()
    
    sys_config, workload_config, filter_config = parse_config_file(args.config_file)
    mr_allocation = parse_resource_config_file(args.resource_config, sys_config)

    # While stress policies can further filter MRs, the first filter is applied here
    # mr_allocation should include only the MRs that are included
    # mr_allocation will provision some percentage of the total resources
    mr_allocation = filter_mr(mr_allocation,
                              sys_config['stress_these_resources'],
                              sys_config['stress_these_services'],
                              sys_config['stress_these_machines'])

    run(sys_config, workload_config, filter_config, mr_allocation)

