import argparse
import requests
import json
import numpy as np
import matplotlib.pyplot as plt
import datetime
import numpy
import timeit
import re
import csv
import ast
import os
from random import shuffle

from time import sleep

from modify_resources import *
from weighting_conversions import *
from causal_analysis import *
from remote_execution import *
from run_experiment import *
from container_information import *
from present_results import *

#Amount of time to allow commands to propagate through system
COMMAND_DELAY = 3

### Start the stresses on the various resources (virtual speedups)

def start_causal_cpu(ssh_client, container_id, disk_rate, network_rate):
    throttle_network(ssh_client, network_rate)
    throttle_disk(ssh_client, container_id, disk_rate)

def start_causal_disk(ssh_client, container_id, cpu_period, cpu_quota, network_rate):
    throttle_cpu(ssh_client, container_id, cpu_period, cpu_quota)
    throttle_network(ssh_client, network_rate)

def start_causal_network(ssh_client, container_id, cpu_period, cpu_quota, disk_rate):
    throttle_cpu(ssh_client, container_id, cpu_period, cpu_quota)
    throttle_disk(ssh_client, container_id, disk_rate)

### Throttle only a single resource at a time.
def throttle_cpu(ssh_client, container_id, cpu_period, cpu_quota):
    # update_cpu_through_stress(ssh_client, number_of_stress)
    set_cpu_quota(ssh_client, container_id, cpu_period, cpu_quota)

def throttle_disk(ssh_client, container_id, disk_rate):
    print 'Disk Throttle Rate: {}'.format(disk_rate)
    return change_container_blkio(ssh_client, container_id, disk_rate)
    # return create_dummy_disk_eater(ssh_client, disk_rate)

# network_bandwidth is a map from interface->bandwidth
def throttle_network(ssh_client, network_bandwidth):
    print 'Network Reduction Rate: {}'.format(network_bandwidth)
    set_network_bandwidth(ssh_client, network_bandwidth)

###Stop the throttling for a single resource
def stop_throttle_cpu(ssh_client, container_id):
    print 'RESETTING CPU THROTTLING'
    reset_cpu_quota(ssh_client, container_id)

def stop_throttle_network(ssh_client):
    print 'RESETTING NETWORK THROTTLING'
    remove_all_network_manipulation(ssh_client)

def stop_throttle_disk(ssh_client, container_id):
    print 'RESETTING DISK THROTTLING'
    change_container_blkio(ssh_client, container_id, 0)
    # remove_dummy_disk_eater(ssh_client, num_fail)

### Revert container to the initial state

def stop_causal_cpu(ssh_client, container_id):
    print 'RESETTING CASUAL CPU!'
    stop_throttle_network(ssh_client)
    stop_throttle_disk(ssh_client, container_id)
    sleep(COMMAND_DELAY)

def stop_causal_disk(ssh_client, container_id):
    print 'RESETTING CASUAL DISK!'
    stop_throttle_network(ssh_client)
    stop_throttle_cpu(ssh_client, container_id)
    sleep(COMMAND_DELAY)

def stop_causal_network(ssh_client, container_id):
    print 'RESETTING CASUAL NETWORK!'
    stop_throttle_cpu(ssh_client, container_id)
    stop_throttle_disk(ssh_client, container_id)
    sleep(COMMAND_DELAY)

def reset_all_stresses(ssh_client, container_id):
    print 'RESETTING ALL STRESSES!'
    stop_throttle_cpu(ssh_client, container_id)
    stop_throttle_disk(ssh_client, container_id)
    stop_throttle_network(ssh_client)
    sleep(COMMAND_DELAY)

# Removes outlier points from the plot
def is_outlier(points, threshold=3.5):
    points = np.array(points)
    if len(points.shape) == 1:
        points = points[:,None]
    median = np.median(points, axis=0)
    diff = np.sum((points - median)**2, axis=-1)
    diff = np.sqrt(diff)
    med_abs_deviation = np.median(diff)

    modified_z_score = 0.6745 * diff / med_abs_deviation

    return modified_z_score > threshold

# Note: Shelved for later
# Initially hardcoded to nginx for convenience
# Should hopefully just need to run once per application
# In the future, can explore a binary search but this is not so simple since runtime is not necessarily growing constantly (or even monotonically), this might be difficult for now
def explore_stress_space(ssh_client, resource, experiment_args, experiment_type, allowable_latency_decrease, allowable_latency_deviation,  measurement_field):

    reset_all_stresses(ssh_client, 0)

    #Take a baseline measurement 20 times (extra since this is a particularly important measurement)
    runtime_array, utilization_diff = measure_runtime(experiment_args, 10, experiment_type)
    print 'The runtime array is {}'.format(runtime_array)
    average_baseline_latency = numpy.mean(runtime_array[measurement_field])

    acceptable_latency_lb = average_baseline_latency + allowable_latency_decrease - allowable_latency_deviation
    acceptable_latency_ub = average_baseline_latency + allowable_latency_decrease + allowable_latency_deviation

    print 'Baseline latency {}'.format(average_baseline_latency)
    print 'lower bound {}'.format(acceptable_latency_lb)
    print 'upper bound {}'.format(acceptable_latency_ub)

    if acceptable_latency_lb < 0:
        print 'Failure: Please input a smaller allowable latency decrease or allowable latency deviation'
        exit()

    if resource == 'cpu':
        #CPU
        print 'STARTING CPU -----------------------------------------'
        num_cores = get_num_cores(ssh_client)
        cpu_list = range(0, 10 * num_cores+1)
        max_stress_index = binary_search(cpu_list, 'cpu', acceptable_latency_lb, acceptable_latency_ub, experiment_args, experiment_type, measurement_field)
        cpu = cpu_list[max_stress_index]
        return cpu
    elif resource == 'disk':
        #Disk
        print 'STARTING DISK -----------------------------------------'
        num_cores = get_num_cores(ssh_client)
        max_disk = get_disk_capabilities(ssh_client, 100)
        disk_list = range(0, max_disk * num_cores + 1)
        max_stress_index = binary_search(disk_list, 'disk', acceptable_latency_lb, acceptable_latency_ub, experiment_args, experiment_type, measurement_field)
        disk = disk_list[max_stress_index]
        return disk
    elif resource == 'network':
        #Network
        print 'STARTING NETWORK -----------------------------------------'
        container_to_network_bandwidth = get_network_capabilities(ssh_client)
        max_bandwidth = container_to_network_bandwidth.itervalues().next()
        #Assumse monotonically increasing
        bandwidth_list = range(max_bandwidth)
        #TODO: should this be bandwidth_list in the function call below?
        max_stress_index = binary_search(parameter_list, 'network', acceptable_latency_lb, acceptable_latency_ub, experiment_args, experiment_type, measurement_field)
        network = bandwidth_list[max_stress_index]
        return network
    else:
        print 'Invalid resource'
        return

# Note: Shelved for later
def linear_search(parameter_list, field, acceptable_latency_lb, acceptable_latency_ub, experiment_args, experiment_type, metric):
    return

# Note: Shelved for later
def binary_search(parameter_list, field, acceptable_latency_lb, acceptable_latency_ub, experiment_args, experiment_type, metric):
    min_index = 0
    max_index = len(parameter_list) - 1
    counter = 0

    while(counter < len(parameter_list)):
        guess = (min_index + max_index) / 2
        print 'the guess is {}'.format(guess)
        print 'min index is {}'.format(min_index)
        print 'max index is {}'.format(max_index)

        num_disk_eaters = 0
        if field == 'network':
            throttle_network(ssh_client, parameter_list[guess])
        if field == 'disk':
            num_disk_eaters = throttle_disk(ssh_client, parameter_list[guess])
        elif field == 'cpu':
            throttle_cpu(ssh_client, parameter_list[guess])

        #Assumes monotonically increasing performance times
        runtime_array,_ = measure_runtime(experiment_args, 1, experiment_type)
        mean = numpy.mean(runtime_array[metric])
        print 'With stress, the mean is {}'.format(mean)

        if field == 'network':
            stop_throttle_network(ssh_client)
        elif field == 'disk':
            stop_throttle_disk(ssh_client, num_disk_eaters)
        elif field == 'cpu':
            stop_throttle_cpu(ssh_client)

        if mean > acceptable_latency_lb and mean < acceptable_latency_ub:
            return guess
        elif mean < acceptable_latency_lb:
            min_index = guess + 1
            continue
        elif mean > acceptable_latency_ub:
            max_index = guess - 1
            continue

        counter += 1

def model_machine(victim_machine, container_id, experiment_args, experiment_iterations, experiment_type, use_causal_analysis, only_baseline):
    ssh_client = quilt_ssh(victim_machine)
    #Start by clearing all the previous perturbations in case something went wrong

    # initialize_machine(ssh_client) LEGACY
    reset_all_stresses(ssh_client, container_id)

    increments = [20, 40, 60, 80]
    shuffle(increments)
    reduction_level_to_latency_network = {}
    reduction_level_to_latency_disk = {}
    reduction_level_to_latency_cpu = {}

    reduction_level_to_utilization_network = {}
    reduction_level_to_utilization_disk = {}
    reduction_level_to_utilization_cpu = {}

    #Take baseline measurements: no perturbations!'''
    BASELINE_ITERATIONS = 15
    baseline_runtime_array, baseline_utilization_diff = measure_runtime(container_id, experiment_args, BASELINE_ITERATIONS, experiment_type)
    reduction_level_to_latency_network[0] = baseline_runtime_array
    reduction_level_to_latency_disk[0] = baseline_runtime_array
    reduction_level_to_latency_cpu[0] = baseline_runtime_array

    reduction_level_to_utilization_network[0] = baseline_utilization_diff
    reduction_level_to_utilization_disk[0] = baseline_utilization_diff
    reduction_level_to_utilization_cpu[0] = baseline_utilization_diff

    if only_baseline:
        return reduction_level_to_latency_cpu, reduction_level_to_latency_disk, reduction_level_to_latency_network

    for increment in increments:

        print 'Experiment with increment={}'.format(increment)

        print '====================================='
        print 'INITIATING CPU Experiment'
        num_full_disk = 0
        if use_causal_analysis:
            disk_throttle_rate = weighting_to_disk_access_rate(increment)
            container_to_network_capacity = get_container_network_capacity(ssh_client, container_id)
            network_reduction_rate = weighting_to_bandwidth(ssh_client, increment, container_to_network_capacity)
            start_causal_cpu(ssh_client, container_id, disk_throttle_rate, network_reduction_rate)
        else:
            cpu_throttle_quota = weighting_to_cpu_quota(increment)
            throttle_cpu(ssh_client, container_id, 1000000, cpu_throttle_quota)
        results_data_cpu, cpu_utilization_diff = measure_runtime(container_id, experiment_args, experiment_iterations, experiment_type)
        if use_causal_analysis:
            stop_causal_cpu(ssh_client, container_id)
        else:
            stop_throttle_cpu(ssh_client, container_id)
        reduction_level_to_latency_cpu[increment] = results_data_cpu
        reduction_level_to_utilization_cpu[increment] = cpu_utilization_diff

        print '======================================'
        print 'INITIATING Network Experiment'
        if use_causal_analysis:
            disk_throttle_rate = weighting_to_disk_access_rate(increment)
            cpu_throttle_quota = weighting_to_cpu_quota(increment)
            start_causal_network(ssh_client, container_id, 1000000, cpu_throttle_quota, disk_throttle_rate)
        else:
            container_to_network_capacity = get_container_network_capacity(ssh_client, container_id)
            network_reduction_rate = weighting_to_bandwidth(ssh_client, increment, container_to_network_capacity)
            throttle_network(ssh_client, network_reduction_rate)
        results_data_network, network_utilization_diff = measure_runtime(container_id, experiment_args, experiment_iterations, experiment_type)

        if use_causal_analysis:
            stop_causal_network(ssh_client, container_id)
        else:
            stop_throttle_network(ssh_client)
        reduction_level_to_latency_network[increment] = results_data_network
        reduction_level_to_utilization_network[increment] = network_utilization_diff

        print '======================================='
        print 'INITIATING Disk Experiment '
        if use_causal_analysis:
            cpu_throttle_quota = weighting_to_cpu_quota(increment)
            container_to_network_capacity = get_container_network_capacity(ssh_client, container_id)
            network_reduction_rate = weighting_to_bandwidth(ssh_client, increment, container_to_network_capacity)
            start_causal_disk(ssh_client, container_id, 1000000, cpu_throttle_quota, network_reduction_rate)
        else:
            disk_throttle_rate = weighting_to_disk_access_rate(increment)
            throttle_disk(ssh_client, container_id, disk_throttle_rate)
        results_data_disk, disk_utilization_diff = measure_runtime(container_id, experiment_args, experiment_iterations, experiment_type)
        if use_causal_analysis:
            stop_causal_disk(ssh_client, container_id)
        else:
            stop_throttle_disk(ssh_client, container_id)
        reduction_level_to_latency_disk[increment] = results_data_disk
        reduction_level_to_utilization_disk[increment] = disk_utilization_diff

    '''
    if use_causal_analysis:
        for key in sorted(results.iterkeys()):
            if key != 0:
                reduction_level_to_latency_disk = calculate_total_delay_added(container_id, reduction_level_to_latency_disk['latency'], reduction_level_to_utilization_disk, key, 'Disk')
                reduction_level_to_latency_cpu = calculate_total_delay_added(container_id, reduction_level_to_latency_cpu['latency'], reduction_level_to_utilization_cpu, key, 'CPU')
                reduction_level_to_latency_network = calculate_total_delay_added(container_id, reduction_level_to_latency_network['latency'], reduction_level_to_utilization_network, key, 'Network')
    '''
    return reduction_level_to_latency_cpu, reduction_level_to_latency_disk, reduction_level_to_latency_network

'''
Experiment arguements takes a list of arguments for the type of experiments
Examples:
"REST": Node TODO App: [public_vm_ip]
"spark-ml-matrix": Spark ml-matrix: [public_vm_ip, private_vm_ip]
"nginx-single": Single unreplicated nginx serving up static pages
'''
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("website_ip", help="Public IP Address that the measurement module will hit with traffic")
    parser.add_argument("victim_machine_public_ip", help="IP Address of server that is beig hit with stress")
    parser.add_argument("victim_machine_private_ip", help="Private (10./) IP Address of server that is being hit with stress")
    parser.add_argument("traffic_generator_public_ip", help="Public IP Address from where synthetic traffic is generated from")
    parser.add_argument("container_id", help="ID of the Container being stressed")
    parser.add_argument("experiment_type", help="Options: spark-ml-matrix, nginx-single, REST")
    parser.add_argument("--iterations", type=int, default=10, help="Number of HTTP requests to send the REST server per experiment")
    parser.add_argument("--use_causal_analysis", action="store_true", help="Set this option to stress only a single variable")
    parser.add_argument("--only_baseline", action="store_true", help="Only takes a measurement of the baseline without any stress")

    args = parser.parse_args()
    print args

    ssh_client = quilt_ssh(args.victim_machine_public_ip)

#    experiment_args = [args.website_ip, args.traffic_generator_public_ip]
#    explore_stress_space(ssh_client, 'disk', experiment_args, args.experiment_type, 4000, 250, 'latency')
#    exit()

    results_disk = {}
    results_cpu = {}
    results_network = {}

    # MESSY TODO: Write an abstract class for the experiment type and implement elsewhere
    if args.experiment_type == 'REST':
        experiment_args = [args.website_ip, args.victim_machine_public_ip]
        results_cpu, results_disk, results_network = model_machine(args.victim_machine_public_ip, args.container_id, experiment_args, args.iterations, args.experiment_type, args.use_causal_analysis, args.only_baseline)
    elif args.experiment_type == "spark-ml-matrix":
        #website_ip in this case is the spark master public ip
        experiment_args = [args.website_ip, args.victim_machine_private_ip]
        results_cpu, results_disk, results_network = model_machine(args.victim_machine_public_ip, args.container_id, experiment_args, args.iterations, args.experiment_type, args.use_causal_analysis, args.only_baseline)
    elif args.experiment_type == "nginx-single":
        experiment_args = [args.website_ip, args.traffic_generator_public_ip]
        results_cpu, results_disk, results_network = model_machine(args.victim_machine_public_ip, args.container_id, experiment_args, args.iterations, args.experiment_type, args.use_causal_analysis, args.only_baseline)
    elif args.experiment_type == "todo-app":
        experiment_args = [args.website_ip, args.traffic_generator_public_ip]
        results_cpu, results_disk, results_network = model_machine(args.victim_machine_public_ip, args.container_id, experiment_args, args.iterations, args.experiment_type, args.use_causal_analysis, args.only_baseline)
    else:
        print 'INVALID EXPERIMENT TYPE'
        exit()

    if args.experiment_type == 'REST':
        reset_experiment(args.victim_machine, args.container_id)

    results_in_milli = True
    if args.experiment_type == 'spark-ml-matrix' or args.experiment_type == 'nginx-single':
        results_in_milli = False

    output_file_name = append_results_to_file(results_cpu, results_disk, results_network, args.experiment_type, args.use_causal_analysis, args.iterations)
    plot_results(output_file_name, args.experiment_type, args.iterations, 'save', convertToMilli=results_in_milli, use_causal_analysis=args.use_causal_analysis)
