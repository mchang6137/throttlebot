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
import socket
from random import shuffle

from time import sleep

from stress_analyzer import *
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
    throttle_network(ssh_client, container_id, network_rate)
    throttle_disk(ssh_client, container_id, disk_rate)

def start_causal_disk(ssh_client, container_id, cpu_period, cpu_quota, network_rate, num_cores):
    if num_cores:
        throttle_cpu_cores(ssh_client, container_id, num_cores)
    else:
        throttle_cpu_quota(ssh_client, container_id, cpu_period, cpu_quota)
    throttle_network(ssh_client, container_id, network_rate)

def start_causal_network(ssh_client, container_id, cpu_period, cpu_quota, disk_rate, num_cores):
    if num_cores:
        throttle_cpu_cores(ssh_client, container_id, num_cores)
    else:
        throttle_cpu_quota(ssh_client, container_id, cpu_period, cpu_quota)
    throttle_disk(ssh_client, container_id, disk_rate)

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

###Stop the throttling for a single resource
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

### Revert container to the initial state

def stop_causal_cpu(ssh_client, container_id):
    print 'RESETTING CASUAL CPU!'
    stop_throttle_network(ssh_client, container_id)
    stop_throttle_disk(ssh_client, container_id)
    sleep(COMMAND_DELAY)

def stop_causal_disk(ssh_client, container_id, cpu_cores):
    print 'RESETTING CASUAL DISK!'
    stop_throttle_network(ssh_client, container_id)
    stop_throttle_cpu(ssh_client, container_id, cpu_cores)
    sleep(COMMAND_DELAY)

def stop_causal_network(ssh_client, container_id, cpu_cores):
    print 'RESETTING CASUAL NETWORK!'
    stop_throttle_cpu(ssh_client, container_id, cpu_cores)
    stop_throttle_disk(ssh_client, container_id)
    sleep(COMMAND_DELAY)

def reset_all_stresses(ssh_client, container_id, cpu_cores):
    print 'RESETTING ALL STRESSES!'
    stop_throttle_cpu(ssh_client, container_id, cpu_cores)
    stop_throttle_disk(ssh_client, container_id)
    stop_throttle_network(ssh_client, container_id)
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
            stop_throttle_network(ssh_client, container_id)
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

def model_machine(ssh_clients, container_ids_dict, experiment_inc_args, experiment_iterations, experiment_type,
                  stress_policy, resources, use_causal_analysis, only_baseline, resume_bool, prev_results):

    if not resume_bool:
        reduction_level_to_latency_network = {}
        reduction_level_to_latency_disk = {}
        reduction_level_to_latency_cpu = {}
    else:
        reduction_level_to_latency_cpu, reduction_level_to_latency_disk, reduction_level_to_latency_network = \
            prev_results

    reduction_level_to_utilization_network = {}
    reduction_level_to_utilization_disk = {}
    reduction_level_to_utilization_cpu = {}

    increment_values = experiment_inc_args[0]
    experiment_args = experiment_inc_args[1]

    for service, ip_container_tuples in container_ids_dict.iteritems():
        print 'STRESSING SERVICE {}'.format(service)

        if not resume_bool or (service not in reduction_level_to_latency_cpu):
            reduction_level_to_latency_network_service = {}
            reduction_level_to_latency_disk_service = {}
            reduction_level_to_latency_cpu_service = {}
        else:
            reduction_level_to_latency_network_service = reduction_level_to_latency_network[service]
            reduction_level_to_latency_disk_service = reduction_level_to_latency_disk[service]
            reduction_level_to_latency_cpu_service = reduction_level_to_latency_cpu[service]

        reduction_level_to_utilization_network_service = {}
        reduction_level_to_utilization_disk_service = {}
        reduction_level_to_utilization_cpu_service = {}

        for vm_ip, container_id in ip_container_tuples:
            print 'STRESSING VM_IP {} AND CONTAINER {}'.format(vm_ip, container_id)

            if isinstance(vm_ip, list):
                multiple_containers = True
                multi_size = len(vm_ip)
                container_tag = container_id[0]
            else:
                multiple_containers = False
                container_tag = container_id
                ssh_client = ssh_clients[vm_ip]

            if stress_policy == 'HALVING':
                container_id, resource = container_id
                resources = [resource]

            # initialize_machine(ssh_client) LEGACY
            if multiple_containers:
                for i in range(multi_size):
                    ssh_client = ssh_clients[vm_ip[i]]
                    reset_all_stresses(ssh_client, container_id[i], cpu_cores)
            else:
                reset_all_stresses(ssh_client, container_id, cpu_cores)

            shuffle(increment_values)

            if not resume_bool or (container_tag not in reduction_level_to_latency_cpu_service):
                reduction_level_to_latency_network_container = {}
                reduction_level_to_latency_disk_container = {}
                reduction_level_to_latency_cpu_container = {}
            else:
                reduction_level_to_latency_network_container = reduction_level_to_latency_network_service[container_id]
                reduction_level_to_latency_disk_container = reduction_level_to_latency_disk_service[container_id]
                reduction_level_to_latency_cpu_container = reduction_level_to_latency_cpu_service[container_id]

            reduction_level_to_utilization_network_container = {}
            reduction_level_to_utilization_disk_container = {}
            reduction_level_to_utilization_cpu_container = {}

            BASELINE_ITERATIONS = 10
            # BASELINE_ITERATIONS = 3 # For fast Benchmarking
            experiment_args[0] = vm_ip
            print 'EX ARG 0 {}'.format(experiment_args[0])
            if 0 in increment_values:
                baseline_runtime_array, baseline_utilization_diff = measure_runtime(container_id, experiment_args, BASELINE_ITERATIONS, experiment_type)
                reduction_level_to_latency_network_container[0] = baseline_runtime_array
                reduction_level_to_latency_disk_container[0] = baseline_runtime_array
                reduction_level_to_latency_cpu_container[0] = baseline_runtime_array

                reduction_level_to_utilization_network_container[0] = baseline_utilization_diff
                reduction_level_to_utilization_disk_container[0] = baseline_utilization_diff
                reduction_level_to_utilization_cpu_container[0] = baseline_utilization_diff

            if not only_baseline:
                for increment in increment_values:
                    if increment == 0:
                        continue

                    print 'Experiment with increment={}'.format(increment)

                    if 'CPU' in resources:
                        print '====================================='
                        print 'INITIATING CPU Experiment'
                        if use_causal_analysis:
                            disk_throttle_rate = weighting_to_disk_access_rate(increment)
                            if multiple_containers:
                                for i in range(multi_size):
                                    ssh_client = ssh_clients[vm_ip[i]]
                                    container_to_network_capacity = get_container_network_capacity(ssh_client, container_id[i])
                                    network_reduction_rate = weighting_to_bandwidth(ssh_client, increment, container_to_network_capacity)
                                    start_causal_cpu(ssh_client, container_id[i], disk_throttle_rate, network_reduction_rate)
                            else:
                                container_to_network_capacity = get_container_network_capacity(ssh_client, container_id)
                                network_reduction_rate = weighting_to_bandwidth(ssh_client, increment, container_to_network_capacity)
                                start_causal_cpu(ssh_client, container_id, disk_throttle_rate, network_reduction_rate)
                        else:
                            if multiple_containers:
                                if cpu_cores:
                                    num_cores = weighting_to_cpu_cores(ssh_client, increment)
                                    for i in range(multi_size):
                                        ssh_client = ssh_clients[vm_ip[i]]
                                        throttle_cpu_cores(ssh_client, container_id[i], num_cores)
                                else:
                                    cpu_throttle_quota = weighting_to_cpu_quota(increment)
                                    for i in range(multi_size):
                                        ssh_client = ssh_clients[vm_ip[i]]
                                        throttle_cpu_quota(ssh_client, container_id[i], 1000000, cpu_throttle_quota)
                            else:
                                if cpu_cores:
                                    num_cores = weighting_to_cpu_cores(ssh_client, increment)
                                    throttle_cpu_cores(ssh_client, container_id, num_cores)
                                else:
                                    cpu_throttle_quota = weighting_to_cpu_quota(increment)
                                    throttle_cpu_quota(ssh_client, container_id, 1000000, cpu_throttle_quota)

                        results_data_cpu, cpu_utilization_diff = measure_runtime(container_id, experiment_args, experiment_iterations, experiment_type)

                        if use_causal_analysis:
                            if multiple_containers:
                                for i in range(multi_size):
                                    ssh_client = ssh_clients[vm_ip[i]]
                                    stop_causal_cpu(ssh_client, container_id[i])
                            else:
                                stop_causal_cpu(ssh_client, container_id)
                        else:
                            if multiple_containers:
                                for i in range(multi_size):
                                    ssh_client = ssh_clients[vm_ip[i]]
                                    stop_throttle_cpu(ssh_client, container_id[i], cpu_cores)
                            else:
                                stop_throttle_cpu(ssh_client, container_id, cpu_cores)

                        reduction_level_to_latency_cpu_container[increment] = results_data_cpu
                        reduction_level_to_utilization_cpu_container[increment] = cpu_utilization_diff

                    if 'NET' in resources:
                            print '======================================'
                            print 'INITIATING Network Experiment'
                            try:
                                if use_causal_analysis:
                                    disk_throttle_rate = weighting_to_disk_access_rate(increment)
                                    num_cores = None
                                    if cpu_cores:
                                        num_cores = weighting_to_cpu_cores(ssh_client, increment)
                                    else:
                                        cpu_throttle_quota = weighting_to_cpu_quota(increment)
                                    if multiple_containers:
                                        for i in range(multi_size):
                                            ssh_client = ssh_clients[vm_ip[i]]
                                            start_causal_network(ssh_client, container_id[i], 1000000, cpu_throttle_quota, disk_throttle_rate, num_cores)
                                    else:
                                        start_causal_network(ssh_client, container_id, 1000000, cpu_throttle_quota, disk_throttle_rate, num_cores)
                                else:
                                    if multiple_containers:
                                        for i in range(multi_size):
                                            ssh_client = ssh_clients[vm_ip[i]]
                                            container_to_network_capacity = get_container_network_capacity(ssh_client, container_id[i])
                                            network_reduction_rate = weighting_to_bandwidth(ssh_client, increment,container_to_network_capacity)
                                            throttle_network(ssh_client, container_id[i], network_reduction_rate)
                                    else:
                                        container_to_network_capacity = get_container_network_capacity(ssh_client, container_id)
                                        network_reduction_rate = weighting_to_bandwidth(ssh_client, increment, container_to_network_capacity)
                                        throttle_network(ssh_client, container_id, network_reduction_rate)

                                results_data_network, network_utilization_diff = measure_runtime(container_id, experiment_args, experiment_iterations, experiment_type)

                                if multiple_containers:
                                    if use_causal_analysis:
                                        for i in range(multi_size):
                                            ssh_client = ssh_clients[vm_ip[i]]
                                            stop_causal_network(ssh_client, container_id[i], cpu_cores)
                                    else:
                                        for i in range(multi_size):
                                            ssh_client = ssh_clients[vm_ip[i]]
                                            stop_throttle_network(ssh_client, container_id[i])
                                else:
                                    if use_causal_analysis:
                                        stop_causal_network(ssh_client, container_id, cpu_cores)
                                    else:
                                        stop_throttle_network(ssh_client, container_id)

                                reduction_level_to_latency_network_container[increment] = results_data_network
                                reduction_level_to_utilization_network_container[increment] = network_utilization_diff
                            except:
                                print 'Passed NET'
                                reduction_level_to_latency_network_container[increment] = reduction_level_to_latency_network_container[0]
                                reduction_level_to_utilization_network_container[increment] = reduction_level_to_utilization_network_container[0]
                    if 'DISK' in resources:
                        print '======================================='
                        print 'INITIATING Disk Experiment '
                        if use_causal_analysis:
                            num_cores = None
                            if cpu_cores:
                                num_cores = weighting_to_cpu_cores(ssh_client, increment)
                            else:
                                cpu_throttle_quota = weighting_to_cpu_quota(increment)
                            if multiple_containers:
                                for i in range(multi_size):
                                    ssh_client = ssh_clients[vm_ip[i]]
                                    container_to_network_capacity = get_container_network_capacity(ssh_client, container_id[i])
                                    network_reduction_rate = weighting_to_bandwidth(ssh_client, increment, container_to_network_capacity)
                                    start_causal_disk(ssh_client, container_id[i], 1000000, cpu_throttle_quota, network_reduction_rate, num_cores)
                            else:
                                container_to_network_capacity = get_container_network_capacity(ssh_client, container_id)
                                network_reduction_rate = weighting_to_bandwidth(ssh_client, increment, container_to_network_capacity)
                                start_causal_disk(ssh_client, container_id, 1000000, cpu_throttle_quota, network_reduction_rate, num_cores)
                        else:
                            disk_throttle_rate = weighting_to_disk_access_rate(increment)
                            if multiple_containers:
                                for i in range(multi_size):
                                    ssh_client = ssh_clients[vm_ip[i]]
                                    throttle_disk(ssh_client, container_id[i], disk_throttle_rate)
                            else:
                                throttle_disk(ssh_client, container_id, disk_throttle_rate)

                        results_data_disk, disk_utilization_diff = measure_runtime(container_id, experiment_args, experiment_iterations, experiment_type)

                        if multiple_containers:
                            if use_causal_analysis:
                                for i in range(multi_size):
                                    ssh_client = ssh_clients[vm_ip[i]]
                                    stop_causal_disk(ssh_client, container_id[i], cpu_cores)
                            else:
                                for i in range(multi_size):
                                    ssh_client = ssh_clients[vm_ip[i]]
                                    stop_throttle_disk(ssh_client, container_id[i])
                        else:
                            if use_causal_analysis:
                                stop_causal_disk(ssh_client, container_id, cpu_cores)
                            else:
                                stop_throttle_disk(ssh_client, container_id)

                        reduction_level_to_latency_disk_container[increment] = results_data_disk
                        reduction_level_to_utilization_disk_container[increment] = disk_utilization_diff

                    reduction_level_to_latency_network_service[container_tag] = reduction_level_to_latency_network_container
                    reduction_level_to_latency_disk_service[container_tag] = reduction_level_to_latency_disk_container
                    reduction_level_to_latency_cpu_service[container_tag] = reduction_level_to_latency_cpu_container

                    reduction_level_to_latency_network[service] = reduction_level_to_latency_network_service
                    reduction_level_to_latency_disk[service] = reduction_level_to_latency_disk_service
                    reduction_level_to_latency_cpu[service] = reduction_level_to_latency_cpu_service

                    # Checkpoint
                    file = append_results_to_file(reduction_level_to_latency_cpu, reduction_level_to_latency_disk,
                                                  reduction_level_to_latency_network, resources, increments,
                                                  experiment_type, use_causal_analysis, experiment_iterations, False)
                    print 'Checkpoint file for increment {} is {}'.format(increment, file)

            reduction_level_to_utilization_network_service[container_tag] = reduction_level_to_utilization_network_container
            reduction_level_to_utilization_disk_service[container_tag] = reduction_level_to_utilization_disk_container
            reduction_level_to_utilization_cpu_service[container_tag] = reduction_level_to_utilization_cpu_container

        reduction_level_to_utilization_network[service] = reduction_level_to_utilization_network_service
        reduction_level_to_utilization_disk[service] = reduction_level_to_utilization_disk_service
        reduction_level_to_utilization_cpu[service] = reduction_level_to_utilization_cpu_service

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
    parser.add_argument("website_ip", help="List of public IP Addresses that the measurement module will hit with traffic")
    parser.add_argument("victim_machine_public_ip", help="List of IP Addresses of servers that are hit with stress")
    parser.add_argument("experiment_type", help="Options: spark-ml-matrix, nginx-single, REST")
    parser.add_argument("--victim_machine_private_ip", help="Private (10./) IP Address of server that is being hit with stress")
    parser.add_argument("--traffic_generator_public_ip", help="Public IP Address from where synthetic traffic is generated from")
    parser.add_argument("--services_to_stress", help="List of services to stress on machines")
    parser.add_argument("--stress_all_services", action="store_true", help="Stress all services")
    parser.add_argument("--resources_to_stress", help="List of resources to throttle")
    parser.add_argument("--stress_all_resources", action="store_true", help="Throttle all resources")
    parser.add_argument("--cpu_cores", action="store_true", help="Use CPU core throttling")
    parser.add_argument("--stress_search_policy", help="Type of stress policy")
    parser.add_argument("--iterations", type=int, default=7, help="Number of HTTP requests to send the REST server per experiment")
    parser.add_argument("--use_causal_analysis", action="store_true", help="Set this option to stress only a single variable")
    parser.add_argument("--only_baseline", action="store_true", help="Only takes a measurement of the baseline without any stress")
    parser.add_argument("--increments", help="The increments of stressing")
    parser.add_argument("--resume", help="Resume experiment (need to specify increments)")

    args = parser.parse_args()
    print args

#   ssh_client = get_client(args.victim_machine_public_ip)
#   experiment_args = [args.website_ip, args.traffic_generator_public_ip]
#   explore_stress_space(ssh_client, 'disk', experiment_args, args.experiment_type, 4000, 250, 'latency')
#   exit()

    # Accomodating for wildcards
    if args.stress_all_services:
        services = '*'
    elif args.services_to_stress:
        services = args.services_to_stress.split(',')
    else:
        print 'Please state which services to stress'
        exit()
    if args.stress_all_resources:
        resources = ['CPU', 'DISK', 'NET']
    elif args.resources_to_stress:
        resources = args.resources_to_stress.split(',')
    else:
        print 'Please state which resources to throttle'
        exit()

    if not args.stress_search_policy:
        print 'Please state a stress search policy'
        exit()
    stress_policy = args.stress_search_policy

    # Checking if ip addresses are valid
    ip_addresses = args.victim_machine_public_ip.split(',')
    for ip in ip_addresses:
        try:
            socket.inet_aton(ip)
        except:
            print 'IP {} is invalid'.format(ip)
            exit()

    website_addresses = args.website_ip.split(',')
    for website in website_addresses:
        try:
            socket.inet_aton(website)
        except:
            print 'Website IP {} is invalid'.format(website)
            exit()

    if args.traffic_generator_public_ip:
        try:
            socket.inet_aton(args.traffic_generator_public_ip)
        except:
            print 'Traffic Generator IP {} is invalid'.format(args.traffic_generator_public_ip)
            exit()
        # Installng dependencies on traffic generator client
        traffic_client = get_client(args.traffic_generator_public_ip)
        ssh_exec(traffic_client, 'sudo apt-get install -y apache2-utils')

    # Creating dictionary of SSH CLIENTS
    victim_ips = args.victim_machine_public_ip.split(',')
    ssh_clients = {}
    for victim_ip in victim_ips:
        ssh_clients[victim_ip] = get_client(victim_ip)

    # Retrieving dictionary of container_ids with service names as keys
    container_ids_dict = get_container_ids(ip_addresses, services, resources, stress_policy)

    results_disk = {}
    results_cpu = {}
    results_network = {}

    continue_stressing = True

    # Checking for stress search type
    if stress_policy == 'HALVING' or stress_policy == 'BINARY':
        container_ids_dict1, container_ids_dict2 = container_ids_dict

    # MESSY TODO: Write an abstract class for the experiment type and implement elsewhere
    if args.experiment_type == 'REST':
        experiment_args = [args.website_ip.split(','), ip_addresses]
    elif args.experiment_type == "spark-ml-matrix":
        #website_ip in this case is the spark master public ip
        experiment_args = [args.website_ip.split(','), args.victim_machine_private_ip]
    elif args.experiment_type == "nginx-single":
        experiment_args = [args.website_ip.split(','), args.traffic_generator_public_ip]
    elif args.experiment_type == "todo-app":
        experiment_args = [args.website_ip.split(','), traffic_client]
    elif args.experiment_type == "basic-get":
        experiment_args = [args.website_ip.split(','), traffic_client]
    else:
        print 'INVALID EXPERIMENT TYPE: {}'.format(args.experiment_type)
        exit()

    # Notifying User CPU throttling type
    cpu_cores = args.cpu_cores
    if cpu_cores:
        print 'Using CPU Core Throttling'
    else:
        print 'Using CPU Quota Throttling'

    # Getting increments
    if not args.increments:
        if args.resume:
            print 'If resuming from a previous experiment, please specify increments'
            exit()
        increments = [0, 20, 40, 60, 80]
    else:
        if args.only_baseline:
            print 'Cannot specify increments when only_baseline is true'
            exit()
        string_increments = args.increments.split(',')
        try:
            increments = map(int, string_increments)
        except:
            print 'ERROR: Increments must be integers'
            exit()
    experiment_inc_args = [increments, experiment_args]

    if args.resume:
        try:
            previous_results = read_from_file(args.resume, True)
        except:
            print 'File not found'
            exit()
        resume_boolean = True
    else:
        resume_boolean = False
        previous_results = None

    while continue_stressing:
        # Reset results dictionary for each iteration
        results_disk = {}
        results_cpu = {}
        results_network = {}

        if stress_policy == 'BINARY' or stress_policy == 'HALVING':
            results1 = model_machine(ssh_clients, container_ids_dict1, experiment_inc_args, args.iterations,
                                     args.experiment_type, stress_policy, resources, args.use_causal_analysis,
                                     args.only_baseline, resume_boolean, previous_results)
            results2 = model_machine(ssh_clients, container_ids_dict2, experiment_inc_args, args.iterations,
                                     args.experiment_type, stress_policy, resources, args.use_causal_analysis,
                                     args.only_baseline, resume_boolean, previous_results)
        else: # More will be added as more search policies are implemented
            results = model_machine(ssh_clients, container_ids_dict, experiment_inc_args, args.iterations,
                                    args.experiment_type, stress_policy, resources, args.use_causal_analysis,
                                    args.only_baseline, resume_boolean, previous_results)

        if args.experiment_type == 'REST':
            for service, (vm_ip, container_id) in container_ids_dict:
                reset_experiment(vm_ip, container_id)

        results_in_milli = True
        if args.experiment_type == 'spark-ml-matrix' or args.experiment_type == 'nginx-single':
            results_in_milli = False

        # Revert container_ids_dict if necessary (Allows for modular update function)
        if stress_policy == 'BINARY' or stress_policy == 'HALVING':
            results = (results1, results2)

        # Update container dictionary based on type
        container_ids_dict = get_updated_container_ids(container_ids_dict, results, stress_policy)

        # Checking and updating loop condition if necessarily (based on type)
        if container_ids_dict == None:
            continue_stressing = False
            if stress_policy == 'BINARY' or stress_policy == 'HALVING':
                results, _ = results
            results_cpu, results_disk, results_network = results

    output_file_name = append_results_to_file(results_cpu, results_disk, results_network, resources, increments, args.experiment_type, args.use_causal_analysis, args.iterations, True)
    plot_results(output_file_name, resources, args.experiment_type, args.iterations, 'save', convertToMilli=results_in_milli, use_causal_analysis=args.use_causal_analysis)
