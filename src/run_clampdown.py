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
import signal
from random import shuffle

from time import *
from run_throttlebot import *

from consolidate_services import *
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
class GracefulKiller:
    redis_db = None
    
    def __init__(self, redis_db):
        self.redis_db = redis_db
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)

    def exit_gracefully(self, signum, frame):
        print 'NIMRs have now also been squeezed, printing final values.'
        current_mr_config = resource_datastore.read_all_mr_alloc(self.redis_db)
        for mr in current_mr_config:
            print '{} = {}'.format(mr.to_string(), current_mr_config[mr])

        print_csv_configuration(current_mr_config)
        exit()

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

# Set the current resource configurations withi the actual containers
# Data points in resource_config are expressed in percentage change
def init_resource_config(redis_db, default_mr_config, machine_type, wc):
    print 'Initializing the Resource Configurations in the containers'
    instance_specs = get_instance_specs(machine_type)
    for mr in default_mr_config:
        new_resource_provision = int(default_mr_config[mr])
        if check_change_mr_viability(redis_db, mr, new_resource_provision)[0] is False:
            print 'Initial Resource provisioning for {} is too much. Exiting...'.format(mr.to_string())
            exit()

        # Enact the change in resource provisioning
        resource_modifier.set_mr_provision(mr, new_resource_provision, wc)

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

def finalize_mr_provision(redis_db, mr, new_alloc, wc):
    resource_modifier.set_mr_provision(mr, int(new_alloc), wc)
    old_alloc = resource_datastore.read_mr_alloc(redis_db, mr)
    resource_datastore.write_mr_alloc(redis_db, mr, int(new_alloc))
    update_machine_consumption(redis_db, mr, new_alloc, old_alloc)

def is_performance_degraded(initial_perf, after_perf, optimize_for_lowest, within_x=0):
    perf_improved = is_performance_improved(initial_perf, after_perf, optimize_for_lowest, within_x)
    perf_constant = is_performance_constant(initial_perf, after_perf, within_x)

    if perf_improved is False and perf_constant is False:
        return True
    else:
        return False

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
def seperate_mr(mr_list, baseline_performance, optimize_for_lowest, within_x=0.03):
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

    # Try to steal from the resources that are least impacted
    min_vm_removal, nimr_reduction = determine_reallocation(redis_db,
                                                            colocated_nimr_list,
                                                            vm_to_nimr,
                                                            imr,
                                                            stress_weight,
                                                            target_imr_increase)

    # Remove NIMRs that are stolen from in the critical path
    # NIMRs that do not move the needle on the min_vm_removal are removed
    current_nimr_considered = nimr_reduction.keys()
    for nimr in nimr_reduction:
        current_nimr_considered.remove(nimr)
        compare_vm_removal, compare_nimr_reduction = determine_reallocation(redis_db,
                                                                            current_nimr_considered,
                                                                            vm_to_nimr,
                                                                            imr,
                                                                            stress_weight,
                                                                            target_imr_increase)
        if compare_vm_removal == min_vm_removal:
            nimr_reduction = compare_nimr_reduction
        else:
            current_nimr_considered.append(nimr)

    new_vm_removal,new_nimr_reduction = determine_reallocation(redis_db,
                                                               current_nimr_considered,
                                                               vm_to_nimr,
                                                               imr,
                                                               stress_weight,
                                                               target_imr_increase)
    assert new_vm_removal == min_vm_removal
    nimr_reduction = new_nimr_reduction
    min_vm_removal = new_vm_removal
            
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

def determine_reallocation(redis_db, colocated_nimr_list, vm_to_nimr, imr,
                           stress_weight, target_imr_increase):
    vm_to_removal = {}
    for deployment in imr.instances:
        vm_ip,_ = deployment
        vm_to_removal[vm_ip] = 0
        
    min_vm_removal = 0
    nimr_reduction = {}
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

    return min_vm_removal,nimr_reduction

# Only enact MR resource changes but do not commit them!
def simulate_mr_provisions(redis_db, imr, imr_proposal, nimr_diff_proposal):
    for nimr in nimr_diff_proposal:
        new_nimr_alloc = resource_datastore.read_mr_alloc(redis_db, nimr) + nimr_diff_proposal[nimr]
        print 'Changing NIMR {} from {} to {}'.format(nimr.to_string(), resource_datastore.read_mr_alloc(redis_db, nimr), new_nimr_alloc)
        resource_modifier.set_mr_provision(nimr, int(new_nimr_alloc))

    old_imr_alloc = resource_datastore.read_mr_alloc(redis_db, imr)
    new_imr_alloc = old_imr_alloc + imr_proposal
    print 'changing imr from {} to {}'.format(old_imr_alloc, new_imr_alloc)
    resource_modifier.set_mr_provision(imr, int(new_imr_alloc))

# Revert to nimr allocation to most recently committed values, reverts "simulation"
def revert_simulate_mr_provisions(redis_db, imr, nimr_diff_proposal):
    for nimr in nimr_diff_proposal:
        old_nimr_alloc = resource_datastore.read_mr_alloc(redis_db, nimr)
	resource_modifier.set_mr_provision(nimr, int(old_nimr_alloc))

    old_imr_alloc =	resource_datastore.read_mr_alloc(redis_db, imr)
    resource_modifier.set_mr_provision(imr, int(old_imr_alloc))

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

def runClampdown(sys_config, workload_config, filter_config, default_mr_config, last_completed_iter=0):
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
    nimr_squeeze_only = sys_config['nimr_squeeze_only']
    fill_services_first = sys_config['fill_services_first']
    num_iterations = sys_config['num_iterations']
    error_tolerance = sys_config['error_tolerance']
    known_imr_list = sys_config['known_imr']

    preferred_performance_metric = workload_config['tbot_metric']
    optimize_for_lowest = workload_config['optimize_for_lowest']

    filter_policy= filter_config['filter_policy']

    redis_db = redis.StrictRedis(host=redis_host, port=6379, db=0)
    if last_completed_iter == 0:
        redis_db.flushall()

    killer = GracefulKiller(redis_db)

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

    current_performance = measure_baseline(workload_config,
                                           baseline_trials,
                                           workload_config['include_warmup'])

    current_performance[preferred_performance_metric] = remove_outlier(current_performance[preferred_performance_metric])
    baseline_performance = current_performance[preferred_performance_metric]
    baseline_mean = mean_list(baseline_performance)
    current_time_stop = datetime.datetime.now()
    time_delta = current_time_stop - time_start

    print 'The Baseline performance is {}'.format(baseline_mean)
    with open("reduction_log.txt", "a") as myfile:
        log_line = 'Starting a new iteration of CUTTING \n'
        log_line += 'All measurements are {}\n'.format(baseline_performance)
        log_line += 'Initial Performance is {}\n\n'.format(baseline_mean)
        myfile.write(log_line)

    # Initialize the current configurations
    # Initialize the working set of MRs to all the MRs
    mr_working_set = resource_datastore.get_all_mrs(redis_db)
    for mr in known_imr_list:
        mr_working_set.remove(mr)

    resource_datastore.write_mr_working_set(redis_db, mr_working_set, 0)
    cumulative_mr_count = 0
    experiment_count = last_completed_iter + 1
    recent_nimr_list = []

    # Modified while condition for completion
    while experiment_count < num_iterations:
        recent_performance = -1
        print '\n\n\n\n\n'
        print 'Cutting round number {}'.format(experiment_count)
        # Get a list of MRs to stress in the form of a list of MRs
        actions_taken = {}
        pipeline_to_consider = apply_filtering_policy(redis_db, mr_working_set, experiment_count,
                                                      sys_config, workload_config, filter_config,
                                                      current_performance)

        # If no pipelines are revealed, there are two options.
        # 1.) Reduce the stress weight, will make progress either way
        # 2.) Have more partition parameters 
        # 3.) Just try again with a different random pipeline
        if len(pipeline_to_consider) == 0:
            experiment_count += 1
            new_partitions = filter_config['pipeline_partitions'] + 2
            if new_partitions <= len(mr_working_set):
                filter_config['pipeline_partitions'] = new_partitions
            else:
                filter_config['pipeline_partitions'] = len(mr_working_set)

            with open("reduction_log.txt", "a") as myfile:
                myfile.write('Step {}, no pipelines found, increasing partition size to {}\n'.format(experiment_count, new_partitions))
            continue

        print 'Pipelines to consider are {}'.format(pipeline_to_consider)
        # Iterate through the pipelines and keep clamping down on the pipelines
        for pipeline in pipeline_to_consider:
            print 'Exploring pipeline {}'.format([mr.to_string() for mr in pipeline])
            mr_new_allocation = {}
            mr_original_allocation = {}
            for mr in pipeline:
                current_mr_allocation = resource_datastore.read_mr_alloc(redis_db, mr)
                new_mr_allocation = convert_percent_to_raw(mr, current_mr_allocation, stress_weight)
                resource_modifier.set_mr_provision(mr, new_mr_allocation)
                mr_new_allocation[mr] = new_mr_allocation
                mr_original_allocation[mr] = current_mr_allocation

            current_mean = mean_list(current_performance[preferred_performance_metric])
            experiment_results = measure_runtime(workload_config, experiment_trials)
            preferred_results = experiment_results[preferred_performance_metric]
            new_performance_mean = mean_list(preferred_results)

            if is_performance_degraded(current_mean, new_performance_mean, optimize_for_lowest, error_tolerance):
                # Revert the changes
                for mr in pipeline:
                    resource_modifier.set_mr_provision(mr, mr_original_allocation[mr])
                print 'Failed, trying a new filtering pipeline'
            else:
                # Commit the changes
                for mr in pipeline:
                    print 'MR {} cut from {} to {}'.format(mr.to_string(), mr_original_allocation[mr], mr_new_allocation[mr])
                    resource_datastore.write_mr_alloc(redis_db, mr, mr_new_allocation[mr])
                    update_machine_consumption(redis_db, mr, mr_original_allocation[mr], mr_new_allocation[mr])
                    actions_taken[mr] = mr_new_allocation[mr] - mr_original_allocation[mr]
                recent_performance = new_performance_mean
                    
        # Checkpoint MR configurations and print
        current_mr_config = resource_datastore.read_all_mr_alloc(redis_db)
        print_csv_configuration(current_mr_config)
        experiment_count += 1

        # Test how this could be packed into fewer machines
        # service packing is a map of a machine -> containers running on it
        mimr_resource = known_imr_list[0].resource
        ff_packing, imr_aware_packing = ffd_pack(current_mr_config, machine_type,
                                                 mimr_resource, known_imr_list)

        # Append results to log file
        with open("reduction_log.txt", "a") as myfile:
            result_string = ''
            result_string += 'Round {}\n'.format(experiment_count)
            result_string += 'Updated performance is {}\n'.format(recent_performance)
            result_string += 'FF Packing has {} bins, with placement {}\n'.format(len(ff_packing.keys()), ff_packing)
            result_string += 'IMR aware Packing has {} bins with placement {}\n'.format(len(imr_aware_packing.keys()), imr_aware_packing)
            for mr in actions_taken:
                result_string += 'Action Taken for {} is {}\n'.format(mr.to_string(), actions_taken[mr])
            print 'tuned_config.csv below'
            print 'SERVICE,RESOURCE,AMOUNT,REPR\n'
            for mr in current_mr_config:
                result_string += '{},{},{},RAW\n'.format(mr.service_name, mr.resource, current_mr_config[mr])
            result_string += '\n\n'
	    myfile.write(result_string)

    print_csv_configuration(current_mr_config)
'''    
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
        resource_modifier.set_mr_provision(mr, baseline_alloc, workload_config)

    performance = measure_baseline(workload_config, max(baseline_trials // 2, 1), False)
    performance = remove_outlier(performance[preferred_performance_metric])

    # Revert back to the most updated resource configuration
    for mr in mr_working_set:
        previous_alloc = resource_datastore.read_mr_alloc(redis_db, mr)
        resource_modifier.set_mr_provision(mr, previous_alloc, workload_config)

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
    error_tolerance = sys_config['error_tolerance']

    metric = workload_config['tbot_metric']
    optimize_for_lowest = workload_config['optimize_for_lowest']
    current_performance_mean = mean_list(current_performance[metric])

    successful_steal = []

    for nimr in current_nimr_list:
        current_nimr_alloc = resource_datastore.read_mr_alloc(redis_db, nimr)
        new_alloc = convert_percent_to_raw(nimr, current_nimr_alloc, stress_weight)
        valid_change,valid_change_amount = check_change_mr_viability(redis_db,
                                                                     nimr,
                                                                     new_alloc - current_nimr_alloc)

        if valid_change is False:
            if valid_change_amount == 0:
                continue
            
        new_alloc = current_nimr_alloc + valid_change_amount
        resource_modifier.set_mr_provision(nimr, new_alloc, None)

        nimr_results = measure_runtime(workload_config, experiment_trials)
        nimr_mean = mean_list(nimr_results[metric])

        print 'Current performance is {}'.format(current_performance_mean)
        print 'New performance is {}'.format(nimr_mean)

        is_constant_perf = is_performance_constant(nimr_mean, current_performance_mean, within_x=error_tolerance)
        is_improved_perf = is_performance_improved(nimr_mean, current_performance_mean,
                                                   optimize_for_lowest, within_x = error_tolerance)

        should_retain_change = is_constant_perf or is_improved_perf

        if should_retain_change:
            finalize_mr_provision(redis_db, nimr, new_alloc, workload_config)
            print 'Successfully cut resources from NIMR {}: {} to {}'.format(nimr.to_string(),
                                                                             current_nimr_alloc,
                                                                             new_alloc)
            successful_steal.append(nimr)
        else:
            print 'Unsuccessfully cut resources from NIMR {}: {} to {}'.format(nimr.to_string(),
                                                                               current_nimr_alloc,
                                                                               new_alloc)
            resource_modifier.set_mr_provision(nimr, current_nimr_alloc, None)

    return successful_steal

# Backtrack when you have overstepped the stress levels
def backtrack_overstep(redis_db, workload_config, experiment_count,
                       current_perf, action_taken, error_tolerance):
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
        resource_modifier.set_mr_provision(mr, median_alloc, None)
        median_alloc_perf = measure_runtime(workload_config, experiment_count)
        median_alloc_mean = mean_list(median_alloc_perf[metric])

        # If the median alloc performance is better, rewind the improvement back to this point
        if is_performance_improved(current_perf_float, median_alloc_mean, optimize_for_lowest, within_x=error_tolerance):
            finalize_mr_provision(redis_db, mr, median_alloc, workload_config)

            # Write a summary of the experiment's iterations to Redis
            perf_improvement = median_alloc_mean - current_perf_float
            new_action = {}
            new_action[mr] = median_alloc - new_mr_alloc
            tbot_datastore.write_summary_redis(redis_db, experiment_count, mr,
                                               perf_improvement, new_action,
                                               median_alloc_mean, median_alloc_mean,
                                               0, 0, is_backtrack=True)

            results = tbot_datastore.read_summary_redis(redis_db, experiment_count)
            print 'Results from backtrack are {}'.format(results)
            return median_alloc_perf
        else:
            # Revert to the most recent MR allocation
            resource_modifier.set_mr_provision(mr, new_mr_alloc, None)

    return None

Functions to parse configuration files
Parses Throttlebot config file and the Resource Allocation Configuration File

'''
# Parses the configuration parameters for both Throttlebot and the workload that Throttlebot is running
def parse_clampdown_config_file(config_file):
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
    sys_config['nimr_squeeze_only'] = config.getboolean('Basic', 'nimr_squeeze_only')
    sys_config['num_iterations']  = config.getint('Basic', 'num_iterations')
    sys_config['error_tolerance'] = config.getfloat('Basic', 'error_tolerance')

    all_services = get_actual_services()
    all_resources = get_stressable_resources()

    known_imr_service = config.get('Basic', 'known_imr_service').split(',')
    known_imr_resource = config.get('Basic', 'known_imr_resource').split(',')

    # Check for validity
    assert len(known_imr_service) == len(known_imr_resource)
    
    if len(known_imr_service) != 0 and known_imr_service[0] != '':
        for service_name in known_imr_service:
            if service_name not in all_services:
                print 'Invalid service name in [Basic] field {}'.format(service_name)
                exit()

        for resource in known_imr_resource:
            if resource not in all_resources:
                print 'Invalid resource name in [Basic] field {}'.format(resource)
                exit()

        vm_list = get_actual_vms()
        service_placements = get_service_placements(vm_list)
    
        sys_config['known_imr'] = []
        for index in range(len(known_imr_service)):
            service_name = known_imr_service[index]
            mr = MR(service_name, known_imr_resource[index], service_placements[service_name])
            assert mr not in sys_config['known_imr']
            sys_config['known_imr'].append(mr)
    else:
        sys_config['known_imr'] = []

    fill_services_first = config.get('Basic', 'fill_services_first')
    if fill_services_first == '':
        sys_config['fill_services_first'] = None
        if sys_config['setting_mode'] == 'prem':
            print 'You need to specify some services to try to fill first!'
            exit()
    else:
        sys_config['fill_services_first'] = fill_services_first.split(',')
        for service in sys_config['fill_services_first']:
            if service not in all_services:
                print 'Invalid service name {}. Change your field fill_services_first'.format(service)
                exit()

    # Configuration parameters relating to the filter step
    filter_config['filter_policy'] = config.get('Filter', 'filter_policy')
    assert filter_config['filter_policy'] == 'pipeline' or filter_config['filter_policy'] == 'pipeline_clampdown' or filter_config['filter_policy'] == ''
    
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
'''

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
'''

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config_file", help="Configuration File for Throttlebot Execution")
    parser.add_argument("--resource_config", help='Default Resource Allocation for Throttlebot')
    parser.add_argument("--last_completed_iter", type=int, default=0, help="Last iteration completed")
    args = parser.parse_args()

    sys_config, workload_config, filter_config = parse_clampdown_config_file(args.config_file)
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
        
    experiment_start = time.time()
    runClampdown(sys_config, workload_config, filter_config, mr_allocation, args.last_completed_iter)
    experiment_end = time.time()

    # Record the time and the number of MRs visited
    print 'The experiment runs for a total of {}'.format(experiment_end - experiment_start)
