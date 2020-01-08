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
from modify_configs import init_conf_functions
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
    init_conf_functions(wc, default_mr_config, redis_db)

    core_mr = [mr for mr in default_mr_config if mr.resource == 'CPU-CORE']
    non_core_mr = [mr for mr in default_mr_config if mr.resource != 'CPU-CORE']
    # Makes sure that CPU_CORE MR always come last
    for mr in non_core_mr + core_mr:
        new_resource_provision = int(default_mr_config[mr])
        if check_change_mr_viability(redis_db, mr, new_resource_provision)[0] is False:
            print 'Initial Resource provisioning for {} is too much. Exiting...'.format(mr.to_string())
            exit()

        # Enact the change in resource provisioning
        resource_modifier.set_mr_provision(mr, new_resource_provision, wc, redis_db)

        # Reflect the change in Redis
        resource_datastore.write_mr_alloc(redis_db, mr, new_resource_provision)
        resource_datastore.write_mr_alloc(redis_db, mr, new_resource_provision, "baseline_alloc")
        update_machine_consumption(redis_db, mr, new_resource_provision, 0)

# Initializes the maximum capacity and current consumption of Quilt
def init_cluster_capacities_r(redis_db, machine_type, quilt_overhead):
    print 'Initializing the per machine capacities'
    resource_alloc = get_instance_specs(machine_type)
    min_alloc = get_instance_min_specs()

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
        resource_datastore.write_machine_floor(redis_db, vm_ip, min_alloc)

'''
Tools that are used for experimental purposes in Throttlebot
'''
def finalize_mr_provision(redis_db, mr, new_alloc, wc):
    resource_modifier.set_mr_provision(mr, int(new_alloc), wc, redis_db)
    old_alloc = resource_datastore.read_mr_alloc(redis_db, mr)
    resource_datastore.write_mr_alloc(redis_db, mr, int(new_alloc))
    update_machine_consumption(redis_db, mr, new_alloc, old_alloc)

# Assesses the relative performnace between initial_perf and after_perf
def is_performance_improved(initial_perf, after_perf, optimize_for_lowest, within_x=0):
    if after_perf > initial_perf + (initial_perf * within_x) and optimize_for_lowest is False:
        return True
    elif after_perf < initial_perf - (initial_perf * within_x) and optimize_for_lowest:
        return True
    else:
        return False

def is_performance_constant(initial_perf, after_perf, within_x=0):
    if abs(initial_perf - after_perf) < initial_perf * within_x:
        return True
    else:
        return False

# Takes a list of MRs ordered by score and then returns a list of IMRs and nIMRs
# Deprecated
def seperate_mr(mr_list, baseline_performance, optimize_for_lowest, within_x=0.01):
    imr_list = []
    nimr_list = []

    for mr_result in mr_list:
        mr,exp_performance = mr_result
        perf_diff = exp_performance - baseline_performance
        print 'perf diff is {}'.format(perf_diff)
        print 'leeway is {}'.format(within_x * baseline_performance)

        if is_performance_constant(baseline_performance, exp_performance, within_x):
            nimr_list.append(mr)
        elif is_performance_improved(baseline_performance, exp_performance, optimize_for_lowest, within_x):
            nimr_list.append(mr)
        else:
            imr_list.append(mr)

    return imr_list, nimr_list

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

# Accept how much a particular MR is changed
def check_change_mr_viability(redis_db, mr, change_proposal):
    if change_proposal > 0:
        return check_improve_mr_viability(redis_db, mr, change_proposal)
    if change_proposal < 0:
        return check_decrease_mr_viability(redis_db, mr, change_proposal)
    else:
        assert change_proposal == 0
        return True, change_proposal

# Checks if the current system can support improvements in a particular MR
# Improvement amount is the raw amount a resource is being improved by
# Always leave 10% of system resources available for Quilt
def check_improve_mr_viability(redis_db, mr, proposed_change):
    proposed_change = int(proposed_change)
    max_change = fill_out_resource(redis_db, mr)

    if proposed_change <= max_change:
        return True, proposed_change
    else:
        return False, max_change

# Check if the new MR weight is valid. Note that this does not check the capacity
# against the total resources available on a machine
# You can change the minimums below safely in accordance to application needs.
# returns the validity of the new MR allocation as well as a new, valid, change amount
def check_decrease_mr_viability(redis_db, mr, proposed_change):
    proposed_change = int(proposed_change)
    resource = mr.resource

    current_alloc = resource_datastore.read_mr_alloc(redis_db, mr)
    new_alloc = current_alloc + proposed_change

    min_dict = {
        'CPU-CORE': 1,
        'CPU-QUOTA': 10,
        'DISK': 10,
        'NET':  1,
        'MEMORY': 1
    }

    try:
        if new_alloc >= min_dict[resource]:
            return True, proposed_change
        else:
            valid_change = -1 * (current_alloc - min_dict[resource])
            return False, valid_change
    except KeyError:
        print 'Invalid Resource'
        exit()

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
        print 'WARNING: Improvement proposal is less than 0 (it is {})'.format(improvement_proposal)
        print 'Check out fill_out_resource_debug.txt to help diagnose the problem'

        # get immediate results just by setting the proposal to zero in this case
        improvement_proposal = 0

    return int(improvement_proposal)

# Decrease resource provisions for co-located resources
# nimr_list should be ordered in terms of least impacted MR to most impacted MR
# Assures that every the reduction_proposal will allow every instance of the service to balloon
# It assumes that given a particular IMR, it is not viable to improve that resource.
# In the NIMR list for NIMRs to be de-allocated.
# Returns a list of NIMRs to reduce and the raw amount to reduce each NIMR, and the amount to incease the IMR bu
def create_decrease_nimr_schedule(redis_db, imr, nimr_list, stress_weight, target_imr_increase):
    print 'IMR is {}'.format(imr.to_string())

    pruned_nimr_list = []
    # Filter out NIMRs that are not the same resource type as mr
    for nimr in list(nimr_list):
        print 'NIMR resource: {} '.format(nimr.resource)
        print 'IMR resource: {}'.format(imr.resource)
        if nimr.resource == imr.resource: pruned_nimr_list.append(nimr)

    if len(pruned_nimr_list) == 0:
        return {},0

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
        for nimr in pruned_nimr_list:
            if nimr.service_name in colocated_services:
                vm_to_nimr[vm_ip].append(nimr)

    colocated_nimr_list = []
    for nimr in pruned_nimr_list:
        is_nimr_colocated = False
        for deployment in imr.instances:
            vm_ip, container = deployment
            if nimr in vm_to_nimr[vm_ip]:
                is_nimr_colocated = True
                break
        if is_nimr_colocated:
            colocated_nimr_list.append(nimr)

    vm_to_removal = {}
    for deployment in imr.instances:
        vm_ip,_ = deployment
        vm_to_removal[vm_ip] = 0

    min_vm_removal = 0
    nimr_reduction = {}

    print 'The colocated  nimr list is {}'.format([nimr.to_string() for nimr in colocated_nimr_list])
    # Try to steal from the resources that are least impacted
    for nimr in colocated_nimr_list:
        reduction_multiplier = containers_per_vm(nimr)
        nimr_alloc = resource_datastore.read_mr_alloc(redis_db, nimr)
        new_alloc = convert_percent_to_raw(nimr, nimr_alloc, stress_weight)

        valid_change, valid_change_amount = check_change_mr_viability(redis_db, nimr, new_alloc - nimr_alloc)
        print 'For NIMR {}, the valid change amount is {}'.format(nimr.to_string(), valid_change_amount)
        assert valid_change_amount <= 0

        if valid_change_amount == 0:
            continue

        for vm_ip in vm_to_nimr:
            if nimr not in vm_to_nimr[vm_ip]:
                continue

            vm_to_removal[vm_ip] += valid_change_amount * reduction_multiplier[vm_ip]
            print 'For vm {}, we are adding {}'.format(vm_ip, valid_change_amount * reduction_multiplier[vm_ip])

        nimr_reduction[nimr] = valid_change_amount
        min_vm_removal = min([abs(vm_to_removal[vm_ip]) for vm_ip in vm_to_removal])

        if abs(min_vm_removal) >= abs(target_imr_increase):
            break

    machine_to_imr = containers_per_vm(imr)
    max_imr_containers = max([machine_to_imr[machine_ip] for machine_ip in machine_to_imr])
    proposed_imr_improvement = abs(min_vm_removal) / max_imr_containers
    print 'proposed imr improvement is {}'.format(proposed_imr_improvement)
    assert proposed_imr_improvement >= 0
    if proposed_imr_improvement == 0:
        return {}, 0
    for imr in nimr_reduction:
        assert nimr_reduction[imr] < 0
    return nimr_reduction, proposed_imr_improvement

# Only enact MR resource changes but do not commit them!
def simulate_mr_provisions(redis_db, imr, imr_proposal, nimr_diff_proposal, wc):
    for nimr in nimr_diff_proposal:
        new_nimr_alloc = resource_datastore.read_mr_alloc(redis_db, nimr) + nimr_diff_proposal[nimr]
        print 'Changing NIMR {} from {} to {}'.format(nimr.to_string(), resource_datastore.read_mr_alloc(redis_db, nimr), new_nimr_alloc)
        resource_modifier.set_mr_provision(nimr, int(new_nimr_alloc), wc, redis_db)

    old_imr_alloc = resource_datastore.read_mr_alloc(redis_db, imr)
    new_imr_alloc = old_imr_alloc + imr_proposal
    print 'changing imr from {} to {}'.format(old_imr_alloc, new_imr_alloc)
    resource_modifier.set_mr_provision(imr, int(new_imr_alloc), wc, redis_db)

# Revert to nimr allocation to most recently committed values, reverts "simulation"
def revert_simulate_mr_provisions(redis_db, imr, nimr_diff_proposal, wc):
    for nimr in nimr_diff_proposal:
        old_nimr_alloc = resource_datastore.read_mr_alloc(redis_db, nimr)
        resource_modifier.set_mr_provision(nimr, int(old_nimr_alloc), wc, redis_db)

    old_imr_alloc = resource_datastore.read_mr_alloc(redis_db, imr)
    resource_modifier.set_mr_provision(imr, int(old_imr_alloc), wc, redis_db)

# Commits the changes to Redis datastore
def commit_mr_provision(redis_db, imr, imr_proposal, nimr_diff_proposal):
    for nimr in nimr_diff_proposal:
        old_alloc = resource_datastore.read_mr_alloc(redis_db, nimr)
        new_nimr_alloc = old_alloc + nimr_diff_proposal[nimr]
        resource_datastore.write_mr_alloc(redis_db, nimr, new_nimr_alloc)
        update_machine_consumption(redis_db, nimr, new_nimr_alloc, old_alloc)

    old_imr_alloc = resource_datastore.read_mr_alloc(redis_db, imr)
    new_imr_alloc = old_imr_alloc + imr_proposal
    resource_datastore.write_mr_alloc(redis_db, imr, new_imr_alloc)
    update_machine_consumption(redis_db, imr, new_imr_alloc, old_imr_alloc)

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
        mimr,action_taken,perf_improvement,analytic_perf,current_perf,elapsed_time, cumm_mr, is_backtrack = tbot_datastore.read_summary_redis(redis_db, experiment_count)
        is_backtrack_string = 'normal'
        if is_backtrack == 'True':
            is_backtrack_string = 'backtrack'

        print 'Iteration {}_{}, Mimr = {}, New allocation = {}, Performance Improvement = {}, Analytic Performance = {}, Performance after improvement = {}, Elapsed Time = {}, Cummulative MR = {}'.format(experiment_count, is_backtrack_string, mimr, action_taken, perf_improvement, analytic_perf, current_perf, elapsed_time, cumm_mr)

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
    print("Num trials is {}".format(experiment_trials))
    stress_weight = sys_config['stress_weight']

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
            resource_modifier.set_mr_provision(change_mr, mr_gradient_schedule[change_mr], workload_config, redis_db)

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
            resource_modifier.set_mr_provision(change_mr, mr_revert_gradient_schedule[change_mr], 
                                               workload_config, redis_db)

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
    stress_weight = sys_config['stress_weight']
    improve_weight = sys_config['improve_weight']
    stress_policy = sys_config['stress_policy']
    resource_to_stress = sys_config['stress_these_resources']
    service_to_stress = sys_config['stress_these_services']
    vm_to_stress = sys_config['stress_these_machines']
    machine_type = sys_config['machine_type']
    quilt_overhead = sys_config['quilt_overhead']
    gradient_mode = sys_config['gradient_mode']
    setting_mode = sys_config['setting_mode']
    rerun_baseline = sys_config['rerun_baseline']
    fill_services_first = sys_config['fill_services_first']

    preferred_performance_metric = workload_config['tbot_metric']
    optimize_for_lowest = workload_config['optimize_for_lowest']

    filter_policy= filter_config['filter_policy']
    workload_config['machine_type'] = machine_type

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
            if check_change_mr_viability(redis_db, mr, mr_improvement_proposal)[0]:
                current_mr_alloc = resource_datastore.read_mr_alloc(redis_db, mr)
                new_mr_alloc = mr_improvement_proposal + current_mr_alloc
                finalize_mr_provision(redis_db, mr, new_mr_alloc, workload_config)
                print 'Maxing our resources for on-prem: MR {} increase from {} to {}'.format(mr.to_string(), current_mr_alloc, new_mr_alloc)
    print 'Filled out resources for on-prem mode'

    print '*' * 20
    print 'INFO: INSTALLING DEPENDENCIES'
    install_dependencies(workload_config)

    # Initialize time for data charts
    time_start = datetime.datetime.now()

    print '*' * 20
    print 'INFO: RUNNING BASELINE'

    # Get the Current Performance -- not used for any analysis, just to benchmark progress!!
    current_performance = measure_baseline(workload_config,
                                           baseline_trials,
                                           workload_config['include_warmup'])

    current_performance[preferred_performance_metric] = remove_outlier(current_performance[preferred_performance_metric])
    baseline_performance = current_performance[preferred_performance_metric]
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
                                           np.std(np.array(current_performance[preferred_performance_metric])), 
                                           time_delta.seconds, 0, 
                                           all_results=current_performance[preferred_performance_metric])

    print '============================================'
    print '\n' * 2

    # Initialize the current configurations
    # Initialize the working set of MRs to all the MRs
    mr_working_set = resource_datastore.get_all_mrs(redis_db)
    resource_datastore.write_mr_working_set(redis_db, mr_working_set, 0)
    cumulative_mr_count = 0
    experiment_count = last_completed_iter + 1
    recent_nimr_list = []

    # Modified while condition for completion
    # while experiment_count < 2:
    while True:
        # Calculate the analytic baseline that is used to determine MRs
        analytic_provisions = prepare_analytic_baseline(redis_db, sys_config, stress_weight)
        print 'The Analytic provisions are as follows {}'.format(analytic_provisions)
        for mr in analytic_provisions:
            resource_modifier.set_mr_provision(mr, analytic_provisions[mr], workload_config, redis_db)

        if len(analytic_provisions) != 0:
            analytic_baseline = measure_runtime(workload_config, experiment_trials)
        else:
            analytic_baseline = deepcopy(current_performance)

        analytic_mean = mean_list(analytic_baseline[preferred_performance_metric])
        print 'The analytic baseline is {}'.format(analytic_baseline)
        print 'This current performance is {}'.format(current_performance)
        analytic_baseline[preferred_performance_metric] = remove_outlier(analytic_baseline[preferred_performance_metric])

        # Get a list of MRs to stress in the form of a list of MRs
        mr_to_consider = apply_filtering_policy(redis_db, mr_working_set, experiment_count,
                                                sys_config, workload_config, filter_config)

        for mr in mr_to_consider:
            print '\n' * 2
            print '*' * 20
            print 'Current MR is {}'.format(mr.to_string())
            increment_to_performance = {}
            current_mr_allocation = resource_datastore.read_mr_alloc(redis_db, mr)
            print 'Current MR allocation is {}'.format(current_mr_allocation)

            # Calculate Gradient Schedule and provision resources accordingly
            mr_gradient_schedule = calculate_mr_gradient_schedule(redis_db, [mr],
                                                                  sys_config,
                                                                  stress_weight)
            for change_mr in mr_gradient_schedule:
                resource_modifier.set_mr_provision(change_mr, mr_gradient_schedule[change_mr], workload_config, redis_db)

            experiment_results = measure_runtime(workload_config, experiment_trials)

            preferred_results = experiment_results[preferred_performance_metric]
            mean_result = mean_list(preferred_results)
            tbot_datastore.write_redis_ranking(redis_db, experiment_count,
                                               preferred_performance_metric,
                                               mean_result, mr, stress_weight)

            mr_revert_gradient_schedule = revert_mr_gradient_schedule(redis_db,
                                                                      [mr],
                                                                      sys_config,
                                                                      stress_weight)
            for change_mr in mr_revert_gradient_schedule:
                resource_modifier.set_mr_provision(change_mr, mr_revert_gradient_schedule[change_mr], 
                                                   workload_config, redis_db)

            increment_to_performance[stress_weight] = experiment_results

            # Write the results of the iteration to Redis
            tbot_datastore.write_redis_results(redis_db, mr, increment_to_performance,
                                               experiment_count, preferred_performance_metric)
            print '*' * 20
            print '\n' * 2

        # Timing Information for the purpose of experiments
        current_time_stop = datetime.datetime.now()
        time_delta = current_time_stop - time_start
        cumulative_mr_count += len(mr_to_consider)
        chart_generator.get_summary_mimr_charts(redis_db, workload_config,
                                                current_performance, mr_working_set,
                                                experiment_count, stress_weight,
                                                preferred_performance_metric, time_start)


        # If set, reruns the baseline as a sanity check before the IMR, MIMR is calculated
        if rerun_baseline:
            print "\n\nRunning Baseline Again as Sanity Check"
            acceptable_baseline = 0.3
            baseline_constant = is_baseline_constant(mr_working_set, workload_config, sys_config,
                                                    baseline_performance, acceptable_baseline)

            if baseline_constant is False:
                print "ERROR: System state has changed since baseline. Deviation greater than {0}%".format(acceptable_deviation * 100)
                print "Current: {0}, Initial: {1}".format(mean_list(performance), mean_list(baseline_performance))
                sys.exit("System state has changed since baseline.")

        # Recover the results of the experiment from Redis
        sorted_mr_list = tbot_datastore.get_top_n_mimr(redis_db, experiment_count,
                                                  preferred_performance_metric,
                                                  stress_weight, gradient_mode,
                                                  optimize_for_lowest=optimize_for_lowest,
                                                  num_results_returned=-1)



        # Move back into the normal operating basis by removing the baseline prep stresses
        reverted_analytic_provisions = revert_analytic_baseline(redis_db, sys_config)
        for mr in reverted_analytic_provisions:
            resource_modifier.set_mr_provision(mr, reverted_analytic_provisions[mr], workload_config, redis_db)

        effective_mimr = None
        for mr_index in range(len(sorted_mr_list) - 1):
            current_mimr = sorted_mr_list[mr_index][0]
            nimr_list = [nimr_tuple[0] for nimr_tuple in sorted_mr_list[mr_index+1:][::-1]]
            recent_nimr_list = nimr_list

            print 'Current MIMR is {}'.format(current_mimr.to_string())
            print 'NIMR list consists of {}'.format([nimr.to_string() for nimr in nimr_list])

            action_taken = {}

            imr_improvement_percent = improve_weight
            current_imr_alloc = resource_datastore.read_mr_alloc(redis_db, current_mimr)
            new_imr_alloc = convert_percent_to_raw(current_mimr, current_imr_alloc, imr_improvement_percent)
            imr_improvement_proposal = int(new_imr_alloc - current_imr_alloc)

            # If the the Proposed MR cannot be improved by the proposed amount, there are two options
            # - Max out the resources to fill up the remaining resources on the machine
            # - Resource Stealing from NIMRs
            # Both functions will return VIABLE improvements to the IMR deployment
            nimr_diff_proposal = {}
            imr_improvement_proposal, nimr_diff_proposal = assess_improvement_proposal(redis_db,
                                                                                       current_mimr,
                                                                                       nimr_list,
				                                                       imr_improvement_proposal,
                                                                                       stress_weight)

            print 'IMR improvement proposal is {}'.format(imr_improvement_proposal)
            for nimr in nimr_diff_proposal:
                print 'The nimr decrease for {} is {}'.format(nimr.to_string(), nimr_diff_proposal[nimr])

            # Apply special handling in the scenario that a filter_policy has been set
            if filter_policy is not None and imr_improvement_proposal <= 0:
                # Special actions must be taken when filtering policies have been set
                filtered_nimr_list = find_colocated_nimrs(redis_db, current_mimr,
                                                          mr_working_set, analytic_mean,
                                                          sys_config, workload_config)

                nimr_diff_proposal,imr_improvement_proposal = create_decrease_nimr_schedule(redis_db,
                                                                                            current_mimr,
                                                                                            filtered_nimr_list,
                                                                                            stress_weight,
                                                                                            imr_improvement_weight
                )


            # Try a different MIMR if no additional resources can be culled
            if imr_improvement_proposal == -1:
                action_taken[current_mimr] = 0
                continue

            # Change MR provisions without committing the actions
            simulate_mr_provisions(redis_db, current_mimr, imr_improvement_proposal, nimr_diff_proposal, workload_config)
            simulated_performance = measure_runtime(workload_config, baseline_trials)
            simulated_performance[preferred_performance_metric] = remove_outlier(simulated_performance[preferred_performance_metric])
            simulated_mean = mean_list(simulated_performance[preferred_performance_metric])
            simulated_std = np.std(np.array(simulated_performance[preferred_performance_metric]))

            current_perf_mean = mean_list(current_performance[preferred_performance_metric])
            is_perf_improved = is_performance_improved(current_perf_mean, simulated_mean, optimize_for_lowest, within_x=0.5)
            is_perf_constant = is_performance_constant(current_perf_mean, simulated_mean, within_x=0.3)

            if (is_perf_improved or is_perf_constant) is False:
                print 'Performance went from {} to {}, thus continuing'.format(current_perf_mean, simulated_mean)
                revert_simulate_mr_provisions(redis_db, current_mimr, nimr_diff_proposal, workload_config)
                action_taken[current_mimr] = 0
                continue
            else:
                print 'Performance is constant, so committing the changes'
                commit_mr_provision(redis_db, current_mimr, imr_improvement_proposal, nimr_diff_proposal)
                action_taken = nimr_diff_proposal
                action_taken[current_mimr] = imr_improvement_proposal
                effective_mimr = current_mimr
                break

        if effective_mimr is None:
            print 'There is no NIMR stealing arrangement that makes sense here. Exiting...'
            exit()

        # Test the new performance after potential resource stealing
        improved_performance = simulated_performance
        improved_mean = simulated_mean
        improved_std = simulated_std
        previous_mean = mean_list(current_performance[preferred_performance_metric])
        performance_improvement = simulated_mean - previous_mean

        # Write a summary of the experiment's iterations to Redis
        tbot_datastore.write_summary_redis(redis_db, experiment_count, effective_mimr,
                                           performance_improvement, action_taken,
                                           analytic_mean, improved_mean, improved_std,
                                           time_delta.seconds, cumulative_mr_count,
                                           all_results=simulated_performance[preferred_performance_metric])

        current_performance = improved_performance

        # Generating overall performance improvement
        chart_generator.get_summary_performance_charts(redis_db, workload_config, experiment_count, time_start)

        results = tbot_datastore.read_summary_redis(redis_db, experiment_count)
        print 'Results from iteration {} are {}'.format(experiment_count, results)

        # Checkpoint MR configurations and print
        current_mr_config = resource_datastore.read_all_mr_alloc(redis_db)
        print_csv_configuration(current_mr_config)
        experiment_count += 1

        # Potentially adapt step size if no performance gains observed
        # Do this after step summary for easy debugging
        minimum_step_gap = 0.15
        if is_performance_improved(previous_mean, improved_mean, optimize_for_lowest, within_x=0.01) is False:
            print 'Net performance improvement reported as 0, so initiating a backtrack step'
            new_performance = backtrack_overstep(redis_db,
                                                 workload_config,
                                                 experiment_count,
                                                 current_performance,
                                                 action_taken,
                                                 minimum_step_gap)

            if new_performance:
                current_performance = new_performance

                # Checkpoint MR configurations and print
                current_mr_config = resource_datastore.read_all_mr_alloc(redis_db)
                print_csv_configuration(current_mr_config)
                experiment_count += 1

                print 'Backtrack completed, referred to as experiment {}'.format(experiment_count)

        print_all_steps(redis_db, experiment_count, sys_config, workload_config, filter_config)

    print 'Convergence achieved - start squeezing NIMRs'
    squeeze_nimrs(redis_db, sys_config,
                  workload_config, recent_nimr_list,
                  current_performance)

    print 'NIMRs have now also been squeezed, printing final values.'
    current_mr_config = resource_datastore.read_all_mr_alloc(redis_db)
    for mr in current_mr_config:
        print '{} = {}'.format(mr.to_string(), current_mr_config[mr])

    print_csv_configuration(current_mr_config)

def is_baseline_constant(mr_working_set,
                         workload_config,
                         sys_config,
                         baseline_performance,
                         acceptable_deviation=0.1):

    baseline_trials = sys_config['baseline_trials']
    preferred_performance_metric = workload_config['tbot_metric']

    # Revert to the fixed baseline_alloc
    for mr in mr_working_set:
        baseline_alloc = resource_datastore.read_mr_alloc(redis_db, mr, "baseline_alloc")
        resource_modifier.set_mr_provision(mr, baseline_alloc, workload_config, redis_db)

    performance = measure_baseline(workload_config, max(baseline_trials // 2, 1), False)
    performance = remove_outlier(performance[preferred_performance_metric])

    # Revert back to the most updated resource configuration
    for mr in mr_working_set:
        previous_alloc = resource_datastore.read_mr_alloc(redis_db, mr)
        resource_modifier.set_mr_provision(mr, previous_alloc, workload_config, redis_db)

    if (abs(mean_list(performance) - mean_list(baseline_performance))
                    / mean_list(baseline_performance)) > acceptable_deviation:
        return False
    else:
        return True

# Assess viability of the improvement proposal
# Returns the improvement proposal if it works, otherwise calculate other means of
# provisioning more resources
def assess_improvement_proposal(redis_db,
                                mimr,
                                other_mr_list,
                                imr_improvement_proposal,
                                stress_weight):

    nimr_diff_proposal = {}

    is_viable,possible_improvement = check_change_mr_viability(redis_db, mimr, imr_improvement_proposal)
    if possible_improvement > 0:
        return possible_improvement, {}
    else:
        nimr_diff_proposal,imr_improvement = create_decrease_nimr_schedule(redis_db,
	                                                                   mimr,
                                                                           other_mr_list,
                                                                           stress_weight,
                                                                           imr_improvement_proposal)
        if imr_improvement == 0 and len(nimr_diff_proposal.keys()) == 0:
            return -1, {}
        else:
            return imr_improvement, nimr_diff_proposal

# Squeeze down NIMRs from existing NIMRs
def squeeze_nimrs(redis_db, sys_config,
                  workload_config,
                  current_nimr_list,
                  current_performance):

    baseline_trials = sys_config['baseline_trials']
    experiment_trials = sys_config['trials']
    stress_weight = sys_config['stress_weight']
    improve_weight = sys_config['improve_weight']

    metric = workload_config['tbot_metric']
    current_performance_mean = mean_list(current_performance[metric])

    for nimr in current_nimr_list:
        print 'exploring {}'.format(nimr.to_string())
        current_nimr_alloc = resource_datastore.read_mr_alloc(redis_db, nimr)
        new_alloc = convert_percent_to_raw(nimr, current_nimr_alloc, stress_weight)
        resource_modifier.set_mr_provision(nimr, new_alloc, workload_config, redis_db)

        nimr_results = measure_runtime(workload_config, experiment_trials)
        nimr_mean = mean_list(nimr_results[metric])

        if is_performance_constant(nimr_mean, current_performance_mean, within_x=0.2):
            finalize_mr_provision(redis_db, nimr, new_alloc, workload_config)
            print 'Successfully cut resources from NIMR {}: {} to {}'.format(nimr.to_string(),
                                                                             current_nimr_alloc,
                                                                             new_alloc)
        else:
            resource_modifier.set_mr_provision(nimr, current_nimr_alloc, workload_config, redis_db)

# Backtrack when you have overstepped the stress levels
def backtrack_overstep(redis_db, workload_config, experiment_count,
                       current_perf, action_taken, minimum_step_gap=0.15):
    metric = workload_config['tbot_metric']
    optimize_for_lowest = workload_config['optimize_for_lowest']
    current_perf_float = mean_list(current_perf[metric])

    for mr in action_taken:
        # Skip if action taken was to steal from a NIMR
        if action_taken[mr] <= 0:
            continue

        new_mr_alloc = resource_datastore.read_mr_alloc(redis_db, mr)
        old_mr_alloc = new_mr_alloc - action_taken[mr]
        median_alloc = old_mr_alloc + (new_mr_alloc - old_mr_alloc) / 2
        resource_modifier.set_mr_provision(mr, median_alloc, workload_config, redis_db)
        median_alloc_perf = measure_runtime(workload_config, experiment_count)
        median_alloc_mean = mean_list(median_alloc_perf[metric])
        median_alloc_std = np.std(np.array(median_alloc_perf[metric]))

        # If the median alloc performance is better, rewind the improvement back to this point
        if is_performance_improved(current_perf_float, median_alloc_mean, optimize_for_lowest, within_x=0.01):
            finalize_mr_provision(redis_db, mr, median_alloc, workload_config)

            # Write a summary of the experiment's iterations to Redis
            perf_improvement = median_alloc_mean - current_perf_float
            new_action = {}
            new_action[mr] = median_alloc - new_mr_alloc
            tbot_datastore.write_summary_redis(redis_db, experiment_count, mr,
                                               perf_improvement, new_action,
                                               median_alloc_mean, median_alloc_mean, median_alloc_std, 
                                               0, 0, is_backtrack=True, all_results=median_alloc_perf[metric])

            results = tbot_datastore.read_summary_redis(redis_db, experiment_count)
            print 'Results from backtrack are {}'.format(results)
            return median_alloc_perf
        else:
            # Revert to the most recent MR allocation
            resource_modifier.set_mr_provision(mr, new_mr_alloc, workload_config, redis_db)

    return None

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
    sys_config['stress_weight'] = config.getint('Basic', 'stress_weight')
    sys_config['improve_weight'] = config.getint('Basic', 'improve_weight')
    sys_config['stress_these_resources'] = config.get('Basic', 'stress_these_resources').split(',')
    sys_config['stress_these_services'] = config.get('Basic', 'stress_these_services').split(',')
    sys_config['stress_these_machines'] = config.get('Basic', 'stress_these_machines').split(',')
    sys_config['redis_host'] = config.get('Basic', 'redis_host')
    sys_config['stress_policy'] = config.get('Basic', 'stress_policy')
    sys_config['machine_type'] = config.get('Basic', 'machine_type')
    sys_config['quilt_overhead'] = config.getint('Basic', 'quilt_overhead')
    sys_config['gradient_mode'] = config.get('Basic', 'gradient_mode')
    sys_config['setting_mode'] = config.get('Basic', 'setting_mode')
    sys_config['rerun_baseline'] = config.getboolean('Basic', 'rerun_baseline')

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
        sys_config['stress_these_services'] = get_actual_services()
    if sys_config['stress_these_machines'] == '*':
        sys_config['stress_these_machines'] = get_actual_vms()

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
        if workload_config['type'] == 'todo-app':
            ssh_exec(traffic_client, 'curl -O https://raw.githubusercontent.com/TsaiAnson/mean-a/master/Master%20Node%20Files/clear_entries.py')
            ssh_exec(traffic_client, 'curl -O https://raw.githubusercontent.com/TsaiAnson/mean-a/master/Master%20Node%20Files/post.json')
        close_client(traffic_client)

    # Hardcoded for apt-app, initializing databases
    if workload_config['type'] == 'apt-app':
        # if len(traffic_machines) != 6:
        #     print 'Not enough traffic machines supplied. Please check config file. Exiting...'
        #     exit()
        # for traffic_machine in traffic_machines:
        #     traffic_client = get_client(traffic_machine)
        #     ssh_exec(traffic_client, 'touch post.json')
        #     close_client(traffic_client)
        traffic_client = get_client(traffic_machines[0])
        ssh_exec(traffic_client, 'touch post.json')
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

    run(sys_config, workload_config, filter_config, mr_allocation, args.last_completed_iter)
