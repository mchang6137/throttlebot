import argparse
import requests
import json
import numpy as np
import datetime
import timeit
import re
import csv
import ast
import os
import socket
import ConfigParser
import math
from random import shuffle

from time import sleep

from copy import deepcopy
from collections import namedtuple
from collections import Counter 
from mr_gradient import *
from stress_analyzer import *
from weighting_conversions import *
from remote_execution import *
from run_experiment import *
from container_information import *
from filter_policy import *
from poll_cluster_state import *
from instance_specs import *
from mr	import MR

import redis.client
import redis_client as tbot_datastore
import redis_resource as resource_datastore
import modify_resources as resource_modifier
import visualizer as chart_generator

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
def init_resource_config(redis_db, default_mr_config, machine_type, wc):
    print 'Initializing the Resource Configurations in the containers'
    instance_specs = get_instance_specs(machine_type)
    for mr in default_mr_config:
        new_resource_provision = int(default_mr_config[mr])
        if check_improve_mr_viability(redis_db, mr, new_resource_provision) is False:
            print 'Initial Resource provisioning for {} is too much. Exiting...'.format(mr.to_string())
            exit()
            
        # Enact the change in resource provisioning
        resource_modifier.set_mr_provision(mr, new_resource_provision, wc)

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
        quilt_usage[resource] = int(((quilt_overhead)/100.0) * max_cap)
    
    all_vms = get_actual_vms()

    for vm_ip in all_vms:
        resource_datastore.write_machine_consumption(redis_db, vm_ip, quilt_usage)
        resource_datastore.write_machine_capacity(redis_db, vm_ip, resource_alloc)

''' 
Tools that are used for experimental purposes in Throttlebot 
'''

def finalize_mr_provision(redis_db, mr, new_alloc, wc):
    resource_modifier.set_mr_provision(mr, int(new_alloc), wc)
    old_alloc = resource_datastore.read_mr_alloc(redis_db, mr)
    resource_datastore.write_mr_alloc(redis_db, mr, int(new_alloc))
    update_machine_consumption(redis_db, mr, new_alloc, old_alloc)

# Takes a list of MRs ordered by score and then returns a list of IMRs and nIMRs
def seperate_mr(mr_list, baseline_performance, optimize_for_lowest, within_x=0.03):
    imr_list = []
    nimr_list = []
    
    for mr_result in mr_list:
        mr,exp_performance = mr_result
        perf_diff = exp_performance - baseline_performance
        print 'perf diff is {}'.format(perf_diff)
        print 'leeway is {}'.format(within_x * baseline_performance)

        if (perf_diff > within_x * baseline_performance) and optimize_for_lowest:
            imr_list.append(mr)
        elif (perf_diff < -1 * within_x * baseline_performance) and optimize_for_lowest is False:
            imr_list.append(mr)
        else:
            nimr_list.append(mr)
            
    return imr_list, nimr_list

# Determine Amount to improve a MIMR
def improve_mr_by(redis_db, mimr, weight_stressed):
    #Simple heuristic currently: Just improve by amount it was improved
    return (weight_stressed * -1)

# Run baseline
def measure_baseline(workload_config, baseline_trials=10, include_warmup=False):
    baseline_runtime_array = measure_runtime(workload_config, baseline_trials, include_warmup)
    return baseline_runtime_array

# Gets the number of containers matching the service in the MR on a particular VM
def containers_per_vm(mr):
    vm_occupancy = []
    for instance in mr.instances:
        vm_ip,container_id = instance
        vm_occupancy.append(vm_ip)
    vm_appearances = Counter(vm_occupancy).most_common(len(vm_occupancy))
        
    improvement_multiplier = {}
    for vm_count in vm_appearances:
        vm_ip, count = vm_count
        improvement_multiplier[vm_ip] = count

    return improvement_multiplier

# Checks if the current system can support improvements in a particular MR
# Improvement amount is the raw amount a resource is being improved by
# Always leave 10% of system resources available for Quilt
def check_improve_mr_viability(redis_db, mr, improvement_amount):
    improvement_amount = int(improvement_amount)
    print 'Checking MR viability'
    improvement_multiplier = containers_per_vm(mr)
    print 'The containers for this mr per vm are {}'.format(improvement_multiplier)
    
    # Check if available space on machines being tested
    for instance in mr.instances:
        vm_ip,container_id = instance
        machine_consumption = resource_datastore.read_machine_consumption(redis_db, vm_ip)
        machine_capacity = resource_datastore.read_machine_capacity(redis_db, vm_ip)

        proposed_alloc = machine_consumption[mr.resource] + (improvement_multiplier[vm_ip] * improvement_amount)
        # Greater than or equal to ensure a meaningless improvement is not attempted
        if proposed_alloc  >= machine_capacity[mr.resource] + (0.01 * machine_capacity[mr.resource]):
            return False
    return True

# Allow the MR to fill out the remainder of the resources on the machine
# Returns the amount to increase the MR by
def fill_out_resource(redis_db, imr):
    improvement_proposal = float('inf')
    improvement_multiplier = containers_per_vm(imr)
    
    for instance in imr.instances:
        vm_ip,container = instance
        consumption = resource_datastore.read_machine_consumption(redis_db, vm_ip)
        capacity = resource_datastore.read_machine_capacity(redis_db, vm_ip)
        diff = capacity[imr.resource] - consumption[imr.resource]
        # Divide diff by the number of containers of that services on that machine
        diff = diff / float(improvement_multiplier[vm_ip])
        if diff < improvement_proposal: improvement_proposal = diff

        debug_statement = 'For vm ip {}, capacity {}, consumption {}, diff {}\n'.format(vm_ip, capacity, consumption, diff)
        with open("fill_out_resource_debug.txt", "a") as myfile:
            myfile.write('imr is {}\n'.format(imr.resource))
            myfile.write('current improvement proposal is {}\n'.format(improvement_proposal))
            myfile.write(debug_statement)
                         
    if improvement_proposal < 0:
        print 'WARNING: Improvement proposal is less than 0 (it is P{})'.format(improvement_proposal)
        print 'Check out fill_out_resource_debug.txt to help diagnose the problem'

        # get immediate results just by setting the proposal to zero in this case
        improvement_proposal = 0
        
    return int(improvement_proposal)

# Decrease resource provisions for co-located resources
# Assures that every the reduction_proposal will allow every instance of the service to balloon
# It assumes that given a particular IMR, it is not viable to improve that resource.
# In the NIMR list for NIMRs to be de-allocated.
# Returns a list of NIMRs to reduce and the raw amount to reduce each NIMR, and the amount to incease the IMR bu
def create_decrease_nimr_schedule(redis_db, imr, nimr_list, stress_weight):
    print 'IMR is {}'.format(imr.to_string())
    
    # Filter out NIMRs that are not the same resource type as mr
    for nimr in list(nimr_list):
        print 'NIMR resource: {} '.format(nimr.resource)
        print 'IMR resource: {}'.format(imr.resource)
        if nimr.resource != imr.resource: nimr_list.remove(nimr)

    if len(nimr_list) == 0:
        return {},0

    print 'NIMR Debugging: Filtered nimr list is {}'.format([nimr.to_string() for nimr in nimr_list])
        
    reduction_proposal = []

    # Ensure that every deployment has at least one service losing a machine
    vm_to_nimr = {}
    vm_to_service = get_vm_to_service(get_actual_vms())

    # Identify an unique list of relevant NIMRs colocated with IMR instances
    for deployment in imr.instances:
        vm_ip, container = deployment
        if vm_ip in vm_to_nimr:
            continue
        
        colocated_services = vm_to_service[vm_ip]
        if imr.service_name in colocated_services: colocated_services.remove(imr.service_name)
        # Remove Duplicates
        colocated_services = list(set(colocated_services))

        vm_to_nimr[vm_ip] = []
        for nimr in nimr_list:
            if nimr.service_name in colocated_services:
                vm_to_nimr[vm_ip].append(nimr)

    min_mr_removal = float('inf')
    target_vm = None
    
    for vm_ip in vm_to_nimr:
        if len(vm_to_nimr[vm_ip]) == 0:
            print 'no suitable NIMRs for substitution found'
            return {}, 0
        total_removal_amount = 0
        for nimr in vm_to_nimr[vm_ip]:
            reduction_multiplier = containers_per_vm(nimr)
            nimr_alloc = resource_datastore.read_mr_alloc(redis_db, nimr)
            new_alloc = convert_percent_to_raw(nimr, nimr_alloc, stress_weight)
            # Multiply by reduction multiplier since you have multiple NIMR instances
            alloc_diff = (nimr_alloc - new_alloc) * reduction_multiplier[vm_ip]
            total_removal_amount += alloc_diff
        if total_removal_amount < min_mr_removal:
            min_mr_removal = total_removal_amount
            target_vm = vm_ip

    new_nimr_change = {}
    total_change = 0
    for nimr in vm_to_nimr[target_vm]:
        reduction_multiplier = containers_per_vm(nimr)
        nimr_alloc = resource_datastore.read_mr_alloc(redis_db, nimr)
        new_alloc = convert_percent_to_raw(nimr, nimr_alloc, stress_weight)
        # Multiply by reduction multiplier since you have multiple NIMR instances
        alloc_diff = (new_alloc - nimr_alloc) * reduction_multiplier[target_vm]
        new_nimr_change[nimr] = int(alloc_diff)
        total_change += alloc_diff

    # Divide the min mr removal amount among the instances on the machine
    improvement_multiplier = containers_per_vm(imr)
    max_multiplier = max(improvement_multiplier.values())
    proposed_imr_improvement = -1 * float(total_change) / max_multiplier
    print 'New MR alloc {}'.format(new_nimr_change)
    print 'Minimum MR Removal {}'.format(proposed_imr_improvement)

    return new_nimr_change, int(proposed_imr_improvement)

# Determine if mr still has an interval to decrease it to
def mr_at_minimum(mr, proposed_weight_change):
    current_alloc = mr.read_mr_alloc(redis_db)
    new_alloc = convert_percent_to_raw(mr, current_alloc, proposed_weight_change)
    if new_alloc == -1:
        return True
    else:
        return False

# Calculate the mean of a list
def mean_list(l):
    return sum(l) / float(len(l))

# Remove Outliers from a list
def remove_outlier(l, n=1):
    n = 1
    no_outlier = [x for x in l if abs(x - np.mean(l)) < np.std(l) * n]
    #hack 
    if len(no_outlier) == 0:
        return l
    return no_outlier

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
def print_all_steps(redis_db, total_experiments, sys_config, workload_config, filter_config):
    print 'Steps towards improving performance'
    net_improvement = 0

    with open("experiment_logs.txt", "a") as myfile:
        log_msg = '{},{},{}\n'.format(sys_config, workload_config, filter_config)
        myfile.write(log_msg)
        
    for experiment_count in range(total_experiments):
        mimr,action_taken,perf_improvement,analytic_perf,current_perf,elapsed_time, cumm_mr = tbot_datastore.read_summary_redis(redis_db, experiment_count)
        print 'Iteration {}, Mimr = {}, New allocation = {}, Performance Improvement = {}, Analytic Performance = {}, Performance after improvement = {}, Elapsed Time = {}, Cummulative MR = {}'.format(experiment_count, mimr, action_taken, perf_improvement, analytic_perf, current_perf, elapsed_time, cumm_mr)

        # Append results to log file
        with open("experiment_logs.txt", "a") as myfile:
            log_msg = '{},{},{},{},{},{}\n'.format(experiment_count, mimr,perf_improvement,elapsed_time, cumm_mr,action_taken)
            myfile.write(log_msg)
            
        net_improvement += float(perf_improvement)
    print 'Net Improvement: {}'.format(net_improvement)

    with open("experiment_logs.txt", "a") as myfile:
        myfile.write('net_improvement,{}\n'.format(net_improvement))

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

# Iterate through all the colocated imrs of the same resource
def find_colocated_nimrs(redis_db, imr, mr_working_set, baseline_mean, sys_config, workload_config):
    print 'Finding colocated NIMRs'
    experiment_trials = sys_config['trials']
    stress_weights = sys_config['stress_weights']
    stress_weight = min(stress_weights)
    
    preferred_performance_metric = workload_config['tbot_metric']
    optimize_for_lowest = workload_config['optimize_for_lowest']
    
    vm_to_service = get_vm_to_service(get_actual_vms())
    
    colocated_services = []
    # Identify an unique list of relevant MRs colocated with IMR instances
    for deployment in imr.instances:
        vm_ip, container = deployment
        colocated_services = colocated_services + vm_to_service[vm_ip]
    print 'Colocated services are {}'.format(colocated_services)
        
    candidate_mrs = []
    for mr in mr_working_set:
        if mr.service_name in colocated_services and mr.resource == imr.resource:
            candidate_mrs.append(mr)
    print 'Candidate MRs are {}'.format([mr.to_string() for mr in candidate_mrs])

    nimr_list = []
    for mr in candidate_mrs:
        print 'MR being considered is {}'.format(mr.to_string())
        mr_gradient_schedule = calculate_mr_gradient_schedule(redis_db, [mr],
                                                              sys_config,
                                                              stress_weight)
            
        for change_mr in mr_gradient_schedule:
            resource_modifier.set_mr_provision(change_mr, mr_gradient_schedule[change_mr], workload_config)
                
        experiment_results = measure_runtime(workload_config, experiment_trials)
        preferred_results = experiment_results[preferred_performance_metric]
        mean_result = mean_list(preferred_results)

        perf_diff = mean_result - baseline_mean
        if (perf_diff > 0.03 * baseline_mean) and optimize_for_lowest:
            print 'Do nothing for optimize lowest'
        elif (perf_diff < -0.03 * baseline_mean) and optimize_for_lowest is False:
            print 'Do nothing for optimize lowest'
        else:
            nimr_list.append(mr)
            
        # Revert the Gradient schedule and provision resources accordingly
        mr_revert_gradient_schedule = revert_mr_gradient_schedule(redis_db,
                                                                  [mr],
                                                                  sys_config,
                                                                  stress_weight)
            
        for change_mr in mr_revert_gradient_schedule:
            resource_modifier.set_mr_provision(change_mr, mr_revert_gradient_schedule[change_mr], workload_config)

    return nimr_list
    
'''
Primary Run method that is called from the main
system_config: Throttlebot related General parameters in a dict
workload_config: Parameters about the workload in a dict
default_mr_config: Filtered MRs that should be stress along with their default allocation
'''

def run(sys_config, workload_config, filter_config, default_mr_config, last_completed_iter=0):
    redis_host = sys_config['redis_host']
    baseline_trials = sys_config['baseline_trials']
    experiment_trials = sys_config['trials']
    stress_weights = sys_config['stress_weights']
    stress_policy = sys_config['stress_policy']
    resource_to_stress = sys_config['stress_these_resources']
    service_to_stress = sys_config['stress_these_services']
    vm_to_stress = sys_config['stress_these_machines']
    machine_type = sys_config['machine_type']
    quilt_overhead = sys_config['quilt_overhead']
    gradient_mode = sys_config['gradient_mode']
    setting_mode = sys_config['setting_mode']
    fill_services_first = sys_config['fill_services_first']
    
    preferred_performance_metric = workload_config['tbot_metric']
    optimize_for_lowest = workload_config['optimize_for_lowest']

    filter_policy= filter_config['filter_policy']

    redis_db = redis.StrictRedis(host=redis_host, port=6379, db=0)
    if last_completed_iter == 0:
        redis_db.flushall()

    print '\n' * 2
    print '*' * 20
    print 'INFO: INITIALIZING RESOURCE CONFIG'
    # Initialize Redis and Cluster based on the default resource configuration
    init_cluster_capacities_r(redis_db, machine_type, quilt_overhead)
    init_service_placement_r(redis_db, default_mr_config)
    init_resource_config(redis_db, default_mr_config, machine_type, workload_config)

    # In the on-prem mode, fill out resources
    if setting_mode == 'prem':
        all_mrs = resource_datastore.get_all_mrs(redis_db)
        priority_mr = []
        
        for mr in all_mrs:
            if mr.service_name in fill_services_first:
                priority_mr.append(mr)

        for mr in priority_mr:
            mr_improvement_proposal = fill_out_resource(redis_db, mr)
            if check_improve_mr_viability(redis_db, mr, mr_improvement_proposal):
                current_mr_alloc = resource_datastore.read_mr_alloc(redis_db, mr)
                new_mr_alloc = mr_improvement_proposal + current_mr_alloc
                finalize_mr_provision(redis_db, mr, new_mr_alloc, workload_config)
                print 'Maxing our resources for on-prem: MR {} increase from {} to {}'.format(mr.to_string(), current_mr_alloc, new_mr_alloc)
    print 'Filled out resources for on-prem mode'
    
    print '*' * 20
    print 'INFO: INSTALLING DEPENDENCIES'
    #install_dependencies(workload_config)

    # Initialize time for data charts
    time_start = datetime.datetime.now()
    
    print '*' * 20
    print 'INFO: RUNNING BASELINE'
    
    # Get the Current Performance -- not used for any analysis, just to benchmark progress!!
    current_performance = measure_baseline(workload_config,
                                           baseline_trials,
                                           workload_config['include_warmup'])

    current_performance[preferred_performance_metric] = remove_outlier(current_performance[preferred_performance_metric])
    current_time_stop = datetime.datetime.now()
    time_delta = current_time_stop - time_start
    
    print 'Current (non-analytic) performance measured: {}'.format(current_performance)

    if last_completed_iter == 0:
        tbot_datastore.write_summary_redis(redis_db,
                                           0,
                                           MR('initial', 'initial', []),
                                           0,
                                           {},
                                           mean_list(current_performance[preferred_performance_metric]),
                                           mean_list(current_performance[preferred_performance_metric]),
                                           time_delta.seconds, 0)
        
    print '============================================'
    print '\n' * 2

    # Initialize the current configurations
    # Initialize the working set of MRs to all the MRs
    mr_working_set = resource_datastore.get_all_mrs(redis_db)
    resource_datastore.write_mr_working_set(redis_db, mr_working_set, 0)
    cumulative_mr_count = 0
    experiment_count = last_completed_iter + 1

    while experiment_count < 10:
        # Calculate the analytic baseline that is used to determine MRs
        analytic_provisions = prepare_analytic_baseline(redis_db, sys_config, min(stress_weights))
        print 'The Analytic provisions are as follows {}'.format(analytic_provisions)
        for mr in analytic_provisions:
            resource_modifier.set_mr_provision(mr, analytic_provisions[mr], workload_config)

        if len(analytic_provisions) != 0:
            analytic_baseline = measure_runtime(workload_config, experiment_trials)
        else:
            analytic_baseline = deepcopy(current_performance)

        analytic_mean = mean_list(analytic_baseline[preferred_performance_metric])
        print 'The analytic baseline is {}'.format(analytic_baseline)
        print 'This current performance is {}'.format(current_performance)
        analytic_baseline[preferred_performance_metric] = remove_outlier(analytic_baseline[preferred_performance_metric])
        
        # Get a list of MRs to stress in the form of a list of MRs
        mr_to_consider = apply_filtering_policy(redis_db,
                                              mr_working_set,
                                              experiment_count,
                                              sys_config,
                                              workload_config,
                                              filter_config)

        for mr in mr_to_consider:
            print '\n' * 2
            print '*' * 20
            print 'Current MR is {}'.format(mr.to_string())
            increment_to_performance = {}
            current_mr_allocation = resource_datastore.read_mr_alloc(redis_db, mr)
            print 'Current MR allocation is {}'.format(current_mr_allocation)
            
            for stress_weight in stress_weights:
                # Calculate Gradient Schedule and provision resources accordingly
                mr_gradient_schedule = calculate_mr_gradient_schedule(redis_db, [mr],
                                                                      sys_config,
                                                                      stress_weight)
                for change_mr in mr_gradient_schedule:
                    resource_modifier.set_mr_provision(change_mr, mr_gradient_schedule[change_mr], workload_config)
                    
                experiment_results = measure_runtime(workload_config, experiment_trials)
                
                # Write results of experiment to Redis
                # preferred_results = remove_outlier(experiment_results[preferred_performance_metric])
                preferred_results = experiment_results[preferred_performance_metric]
                mean_result = mean_list(preferred_results)
                tbot_datastore.write_redis_ranking(redis_db, experiment_count,
                                                   preferred_performance_metric,
                                                   mean_result, mr, stress_weight)

                # Revert the Gradient schedule and provision resources accordingly
                mr_revert_gradient_schedule = revert_mr_gradient_schedule(redis_db,
                                                                          [mr],
                                                                          sys_config,
                                                                          stress_weight)
                for change_mr in mr_revert_gradient_schedule:
                    resource_modifier.set_mr_provision(change_mr, mr_revert_gradient_schedule[change_mr], workload_config)
                    
                increment_to_performance[stress_weight] = experiment_results

            # Write the results of the iteration to Redis
            tbot_datastore.write_redis_results(redis_db, mr, increment_to_performance, experiment_count, preferred_performance_metric)
            print '*' * 20
            print '\n' * 2

        # Timing Information for the purpose of experiments
        current_time_stop = datetime.datetime.now()
        time_delta = current_time_stop - time_start
        cumulative_mr_count += len(mr_to_consider)
        chart_generator.get_summary_mimr_charts(redis_db, workload_config,
                                                current_performance, mr_working_set,
                                                experiment_count, stress_weights,
                                                preferred_performance_metric, time_start)
        
        # Recover the results of the experiment from Redis
        max_stress_weight = min(stress_weights)
        mimr_list = tbot_datastore.get_top_n_mimr(redis_db, experiment_count,
                                                  preferred_performance_metric,
                                                  max_stress_weight, gradient_mode,
                                                  optimize_for_lowest=optimize_for_lowest,
                                                  num_results_returned=-1)

        imr_list, nimr_list = seperate_mr(mimr_list, mean_list(analytic_baseline[preferred_performance_metric]), optimize_for_lowest)
        if len(imr_list) == 0:
            print 'INFO: IMR list length is 0. Please choose a metric with more signal. Exiting...'
            break
        print 'INFO: IMR list is {}'.format([mr.to_string() for mr in imr_list])
        print 'INFO: NIMR list is {}'.format([mr.to_string() for mr in nimr_list])
        
        # Try all the MIMRs in the list until a viable improvement is determined
        # Improvement Amount
        mimr = None
        action_taken = {}
        
        for imr in imr_list:
            imr_improvement_percent = improve_mr_by(redis_db, imr, max_stress_weight)
            current_imr_alloc = resource_datastore.read_mr_alloc(redis_db, imr)
            new_imr_alloc = convert_percent_to_raw(imr, current_imr_alloc, imr_improvement_percent)
            imr_improvement_proposal = int(new_imr_alloc - current_imr_alloc)

            # If the the Proposed MR cannot be improved by the proposed amount, there are two options
            # - Max out the resources to fill up the remaining resources on the machine
            # - Resource Stealing from NIMRs
            # Both functions will return VIABLE improvements to the IMR deployment
            nimr_diff_proposal = {}
            if check_improve_mr_viability(redis_db, imr, imr_improvement_proposal) is False:
                print 'INFO: MR {} to increase {} by {} is not viable'.format(imr.to_string(),
                                                                              current_imr_alloc,
                                                                              imr_improvement_proposal)
                print 'INFO: Attempting to max out the machines resources...'
                imr_improvement_proposal = fill_out_resource(redis_db, imr)

                if imr_improvement_proposal <= 0:
                    print 'INFO: No more space to fill out resources. Stealing from NIMRs'
                    # Calculate a plan to reduce the resource provisioning of NIMRs
                    nimr_diff_proposal,imr_improvement_proposal = create_decrease_nimr_schedule(redis_db,
                                                                                                imr,
                                                                                                nimr_list,
                                                                                                max_stress_weight)
                    print 'INFO: Proposed NIMR {}'.format(nimr_diff_proposal)
                    print 'INFO: New IMR improvement {}'.format(imr_improvement_proposal)
                    
                    if len(nimr_diff_proposal) == 0 or imr_improvement_proposal == 0:
                        if filter_policy is None:
                            action_taken[imr] = 0
                            continue

                        # Special actions for Filtered results
                        filtered_nimr_list = find_colocated_nimrs(redis_db, imr, mr_working_set, analytic_mean, sys_config, workload_config)
                        nimr_diff_proposal,imr_improvement_proposal = create_decrease_nimr_schedule(redis_db,
                                                                                                    imr,
                                                                                                    filtered_nimr_list,
                                                                                                    max_stress_weight)
                        if len(nimr_diff_proposal) == 0 or imr_improvement_proposal == 0:
                            continue
                        
            # Decrease the amount of resources provisioned to the NIMR
            for nimr in nimr_diff_proposal:
                action_taken[nimr] = nimr_diff_proposal[nimr]
                new_nimr_alloc = resource_datastore.read_mr_alloc(redis_db, nimr) + nimr_diff_proposal[nimr]
                print 'NIMR stealing: imposing a change of {} on {}'.format(action_taken[nimr],
                                                                            nimr.to_string())
                finalize_mr_provision(redis_db, nimr, new_nimr_alloc, workload_config)

            print 'Taking an accounting before decreasing...'
            print 'IMR {} is currently at {}, trying to improve by {}'.format(imr.to_string(), current_imr_alloc, imr_improvement_proposal)
            # Improving the resource should always be viable at this step
            if check_improve_mr_viability(redis_db, imr, imr_improvement_proposal):
                new_imr_alloc = imr_improvement_proposal + current_imr_alloc
                action_taken[imr] = imr_improvement_proposal
                finalize_mr_provision(redis_db, imr, new_imr_alloc, workload_config)
                print 'Improvement Calculated: MR {} increase from {} to {}'.format(imr.to_string(), current_imr_alloc, new_imr_alloc)
                mimr = imr
                break
            else:
                action_taken[imr] = 0
                new_imr_alloc = imr_improvement_proposal + current_imr_alloc
                print 'Improvement Calculated: MR {} failed to improve from {} to {}'.format(imr.to_string(),
                                                                                             current_imr_alloc,
                                                                                             imr_improvement_proposal)
                print 'This IMR cannot be improved. Printing some debugging before exiting...'

                print 'Current MR allocation is {}'.format(current_imr_alloc)
                print 'Proposed (failed) allocation is {}, improved by {}'.format(new_imr_alloc, imr_improvement_proposal)

                for deployment in imr.instances:
                    vm_ip,container = deployment
                    capacity = resource_datastore.read_machine_capacity(redis_db, vm_ip)
                    consumption = resource_datastore.read_machine_consumption(redis_db, vm_ip)
                    print 'Machine {} Capacity is {}, and consumption is currently {}'.format(vm_ip, capacity, consumption)

        if mimr is None:
            print 'No viable improvement found'
            break

        # Move back into the normal operating basis by removing the baseline prep stresses
        reverted_analytic_provisions = revert_analytic_baseline(redis_db, sys_config)
        for mr in reverted_analytic_provisions:
            resource_modifier.set_mr_provision(mr, reverted_analytic_provisions[mr], workload_config)

        #Compare against the baseline at the beginning of the program
        improved_performance = measure_runtime(workload_config, baseline_trials)
        # improved_performance[preferred_performance_metric] = remove_outlier(improved_performance[preferred_performance_metric])
        improved_mean = mean_list(improved_performance[preferred_performance_metric]) 
        previous_mean = mean_list(current_performance[preferred_performance_metric])
        performance_improvement = improved_mean - previous_mean
        
        # Write a summary of the experiment's iterations to Redis
        tbot_datastore.write_summary_redis(redis_db, experiment_count, mimr,
                                           performance_improvement, action_taken,
                                           analytic_mean, improved_mean,
                                           time_delta.seconds, cumulative_mr_count) 
        current_performance = improved_performance

        # Generating overall performance improvement
        chart_generator.get_summary_performance_charts(redis_db, workload_config, experiment_count, time_start)

        results = tbot_datastore.read_summary_redis(redis_db, experiment_count)
        print 'Results from iteration {} are {}'.format(experiment_count, results)

        # Checkpoint MR configurations and print
        current_mr_config = resource_datastore.read_all_mr_alloc(redis_db) 
        print_csv_configuration(current_mr_config)
        experiment_count += 1

    print '{} experiments completed'.format(experiment_count)
    print_all_steps(redis_db, experiment_count, sys_config, workload_config, filter_config)

    current_mr_config = resource_datastore.read_all_mr_alloc(redis_db)
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
    sys_config['gradient_mode'] = config.get('Basic', 'gradient_mode')
    sys_config['setting_mode'] = config.get('Basic', 'setting_mode')
    fill_services_first = config.get('Basic', 'fill_services_first')
    if fill_services_first == '':
        sys_config['fill_services_first'] = None
        if sys_config['setting_mode'] == 'on_prem':
            print 'You need to specify some services to try to fill first!'
            exit()
    else:
        sys_config['fill_services_first'] = fill_services_first.split(',')
        all_services = get_actual_services()
        for service in sys_config['fill_services_first']:
            if service not in all_services:
                print 'Invalid service name {}. Change your field fill_services_first'.format(service)
                exit()

    # Configuration parameters relating to the filter step
    filter_config['filter_policy'] = config.get('Filter', 'filter_policy')
    if filter_config['filter_policy'] == '':
        filter_config['filter_policy'] = None
    filter_config['pipeline_partitions'] = config.getint('Filter', 'pipeline_partitions')
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
    if sys_config['gradient_mode'] == 'inverted':
        # kind of a hack. If we are doing the inverted stressing for gradient, we actually want to optimize for the most effective.
        workload_config['optimize_for_lowest'] = not workload_config['optimize_for_lowest']
    workload_config['performance_target'] = config.get('Workload', 'performance_target')
    workload_config['include_warmup'] = config.getboolean('Workload', 'include_warmup')
    
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
        default_alloc_percentage = 70.0 / max_num_services

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
        elif mr.service_name == 'mchang6137/spark_streaming':
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
    parser.add_argument("--last_completed_iter", type=int, default=0, help="Last iteration completed")
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
    if workload_config['type'] == 'bcd':
        all_vm_ip = get_actual_vms()
        service_to_deployment = get_service_placements(all_vm_ip)
        workload_config['request_generator'] = [service_to_deployment['hantaowang/bcd-spark-master'][0][0]]
        workload_config['frontend'] = [service_to_deployment['hantaowang/bcd-spark-master'][0][0]]
        workload_config['additional_args'] = {'container_id': service_to_deployment['hantaowang/bcd-spark-master'][0][1]}
        workload_config['resources'] = {
            'spark.executor.cores': '8',
            'spark.driver.cores': '8',
            'spark.executor.memory': str(int(32 * 0.8)) + 'g',
            'spark.driver.memory': str(int(32 * 0.8)) + 'g',
            'spark.cores.max': '48'
        }
        workload_config['instances'] = service_to_deployment['hantaowang/bcd-spark'] + service_to_deployment['hantaowang/bcd-spark-master']
        print workload_config

    run(sys_config, workload_config, filter_config, mr_allocation, args.last_completed_iter)

