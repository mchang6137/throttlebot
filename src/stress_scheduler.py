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
import redis

from time import sleep

from stress_analyzer import *
from modify_resources import *
from weighting_conversions import *
from remote_execution import *
from run_experiment import *
from container_information import *
from present_results import *
from run_spark_streaming import *

#Amount of time to allow commands to propagate through system
COMMAND_DELAY = 3

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
                  stress_policy, resources, only_baseline, resume_bool, prev_results,
                  experiment_iteration_count, redis_db):

    # RESUME FUNCTION SHELVED FOR LATER (ALSO OUTDATED)
    if not resume_bool:
        reduction_level_to_latency_network = {}
        reduction_level_to_latency_disk = {}
        reduction_level_to_latency_cpu = {}
    else:
        reduction_level_to_latency_cpu, reduction_level_to_latency_disk, reduction_level_to_latency_network = prev_results

    increment_values = experiment_inc_args[0]
    experiment_args = experiment_inc_args[1]

    # Declaring baseline outside of loop for ALL services
    baseline_runtime_array, baseline_utilization_diff = None, None

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

        # Used for service aliasing (Later implementation)
        service_tag = service

        # OUTDATED
        if stress_policy == 'HALVING':
            container_id, resource = container_id
            resources = [resource]

        # initialize_machine(ssh_client) LEGACY
        print "CLEARING ALL STRESSES"
        print "====================================="
        for service, ip_container_tuples in container_ids_dict.iteritems():
            for vm_ip, container_id in ip_container_tuples:
                ssh_client = ssh_clients[vm_ip]
                reset_all_stresses(ssh_client, container_id, cpu_cores)
        print "FINISHED CLEARING ALL STRESSES"
        print "====================================="
        print '\n' * 4

        shuffle(increment_values)

        BASELINE_ITERATIONS = 10
        # BASELINE_ITERATIONS = 3 # For fast Benchmarking
        if 0 in increment_values:
            # Checking if baseline has been calculated yet
            if baseline_runtime_array == None and baseline_utilization_diff == None:
                baseline_runtime_array = measure_runtime(None, experiment_args, BASELINE_ITERATIONS,
                                                         experiment_type)

            reduction_level_to_latency_network_service[0] = baseline_runtime_array
            hash_name = '{},{},{}'.format(experiment_iteration_count, service_tag, 'NET')
            sorted_set_name = '{},{}'.format(service_tag, 'NET')
            print 'HashName: {}'.format(hash_name)
            print 'SortedSetName: {}'.format(sorted_set_name)
            for metric, data in baseline_runtime_array.iteritems():
                key_name = '{},{}'.format(0, metric)
                sorted_key_name = '{},{}'.format(experiment_iteration_count, key_name)
                redis_db.hset(hash_name, key_name, '{}'.format(data))
                redis_db.zadd(sorted_set_name, numpy.mean(data), sorted_key_name)

            reduction_level_to_latency_disk_service[0] = baseline_runtime_array
            hash_name = '{},{},{}'.format(experiment_iteration_count, service_tag, 'DISK')
            sorted_set_name = '{},{}'.format(service_tag, 'DISK')
            print 'HashName: {}'.format(hash_name)
            print 'SortedSetName: {}'.format(sorted_set_name)
            for metric, data in baseline_runtime_array.iteritems():
                key_name = '{},{}'.format(0, metric)
                sorted_key_name = '{},{}'.format(experiment_iteration_count, key_name)
                redis_db.hset(hash_name, key_name, '{}'.format(data))
                redis_db.zadd(sorted_set_name, numpy.mean(data), sorted_key_name)

            reduction_level_to_latency_cpu_service[0] = baseline_runtime_array
            hash_name = '{},{},{}'.format(experiment_iteration_count, service_tag, 'CPU')
            sorted_set_name = '{},{}'.format(service_tag, 'CPU')
            print 'HashName: {}'.format(hash_name)
            print 'SortedSetName: {}'.format(sorted_set_name)
            for metric, data in baseline_runtime_array.iteritems():
                key_name = '{},{}'.format(0, metric)
                sorted_key_name = '{},{}'.format(experiment_iteration_count, key_name)
                redis_db.hset(hash_name, key_name, '{}'.format(data))
                redis_db.zadd(sorted_set_name, numpy.mean(data), sorted_key_name)

        if not only_baseline:
            for increment in increment_values:
                if increment == 0:
                    continue

                print 'Experiment with increment={}'.format(increment)

                if 'CPU' in resources:
                    print '====================================='
                    print 'INITIATING CPU Experiment'

                    for vm_ip, container_id in ip_container_tuples:
                        print 'STRESSING VM_IP {} AND CONTAINER {}'.format(vm_ip, container_id)
                        ssh_client = ssh_clients[vm_ip]
                        if cpu_cores:
                            num_cores = weighting_to_cpu_cores(ssh_client, increment)
                            throttle_cpu_cores(ssh_client, container_id, num_cores)
                        else:
                            cpu_throttle_quota = weighting_to_cpu_quota(increment)
                            throttle_cpu_quota(ssh_client, container_id, 1000000, cpu_throttle_quota)

                    results_data_cpu = measure_runtime(container_id, experiment_args,
                                                                             experiment_iterations, experiment_type)

                    for vm_ip, container_id in ip_container_tuples:
                        ssh_client = ssh_clients[vm_ip]
                        stop_throttle_cpu(ssh_client, container_id, cpu_cores)

                    reduction_level_to_latency_cpu_service[increment] = results_data_cpu
                    hash_name = '{},{},{}'.format(experiment_iteration_count, service_tag, 'CPU')
                    sorted_set_name = '{},{}'.format(service_tag, 'CPU')
                    print 'HashName: {}'.format(hash_name)
                    print 'SortedSetName: {}'.format(sorted_set_name)
                    for metric, data in results_data_cpu.iteritems():
                        key_name = '{},{}'.format(increment, metric)
                        sorted_key_name = '{},{}'.format(experiment_iteration_count, key_name)
                        redis_db.hset(hash_name, key_name, '{}'.format(data))
                        redis_db.zadd(sorted_set_name, numpy.mean(data), sorted_key_name)

                if 'NET' in resources:
                    print '======================================'
                    print 'INITIATING Network Experiment'
                    try:
                        for vm_ip, container_id in ip_container_tuples:
                            print 'STRESSING VM_IP {} AND CONTAINER {}'.format(vm_ip, container_id)
                            ssh_client = ssh_clients[vm_ip]
                            container_to_network_capacity = get_container_network_capacity(ssh_client, container_id)
                            network_reduction_rate = weighting_to_bandwidth(ssh_client, increment,
                                                                            container_to_network_capacity)
                            throttle_network(ssh_client, container_id, network_reduction_rate)

                        results_data_network = measure_runtime(container_id, experiment_args, experiment_iterations,
                                                               experiment_type)

                        for vm_ip, container_id in ip_container_tuples:
                            ssh_client = ssh_clients[vm_ip]
                            stop_throttle_network(ssh_client, container_id)

                        reduction_level_to_latency_network_service[increment] = results_data_network
                        hash_name = '{},{},{}'.format(experiment_iteration_count, service_tag, 'NET')
                        sorted_set_name = '{},{}'.format(service_tag, 'NET')
                        print 'HashName: {}'.format(hash_name)
                        print 'SortedSetName: {}'.format(sorted_set_name)
                        for metric, data in results_data_network.iteritems():
                            key_name = '{},{}'.format(increment, metric)
                            sorted_key_name = '{},{}'.format(experiment_iteration_count, key_name)
                            redis_db.hset(hash_name, key_name, '{}'.format(data))
                            redis_db.zadd(sorted_set_name, numpy.mean(data), sorted_key_name)
                    except:
                        print 'Passed NET'
                        reduction_level_to_latency_network_service[increment] = \
                            reduction_level_to_latency_network_service[0]
                if 'DISK' in resources:
                    print '======================================='
                    print 'INITIATING Disk Experiment '
                    disk_throttle_rate = weighting_to_disk_access_rate(increment)
                    for vm_ip, container_id in ip_container_tuples:
                        print 'STRESSING VM_IP {} AND CONTAINER {}'.format(vm_ip, container_id)
                        ssh_client = ssh_clients[vm_ip]
                        throttle_disk(ssh_client, container_id, disk_throttle_rate)

                    results_data_disk = measure_runtime(container_id, experiment_args, experiment_iterations,
                                                        experiment_type)

                    for vm_ip, container_id in ip_container_tuples:
                        ssh_client = ssh_clients[vm_ip]
                        stop_throttle_disk(ssh_client, container_id)

                    reduction_level_to_latency_disk_service[increment] = results_data_disk
                    hash_name = '{},{},{}'.format(experiment_iteration_count, service_tag, 'DISK')
                    sorted_set_name = '{},{}'.format(service_tag, 'DISK')
                    print 'HashName: {}'.format(hash_name)
                    print 'SortedSetName: {}'.format(sorted_set_name)
                    for metric, data in results_data_disk.iteritems():
                        key_name = '{},{}'.format(increment, metric)
                        sorted_key_name = '{},{}'.format(experiment_iteration_count, key_name)
                        redis_db.hset(hash_name, key_name, '{}'.format(data))
                        redis_db.zadd(sorted_set_name, numpy.mean(data), sorted_key_name)

                # Saving results
                reduction_level_to_latency_network[service_tag] = reduction_level_to_latency_network_service
                reduction_level_to_latency_disk[service_tag] = reduction_level_to_latency_disk_service
                reduction_level_to_latency_cpu[service_tag] = reduction_level_to_latency_cpu_service

                # File Checkpoint
                file = append_results_to_file(reduction_level_to_latency_cpu, reduction_level_to_latency_disk,
                                              reduction_level_to_latency_network, resources, increments,
                                              experiment_type, experiment_iterations,
                                              experiment_iteration_count, False)
                print 'Checkpoint file for increment {} is {}'.format(increment, file)

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
    parser.add_argument("--only_baseline", action="store_true", help="Only takes a measurement of the baseline without any stress")
    parser.add_argument("--increments", help="The increments of stressing")
    parser.add_argument("--resume", help="Resume experiment (need to specify increments)")
    parser.add_argument("--redis_ms", help="IP of Redis Machine")
    parser.add_argument("--spark_stream", help ="IP of Spark Stream")
    parser.add_argument("--kafka", help="IP of Kafka machine")
    parser.add_argument("--spark_ms", help="IP of spark-ms ")
    parser.add_argument("--spark_wk", help="IPs of spark workers")
    parser.add_argument("--multiservice_stressing", help="Lists of services to be stressed together")


    args = parser.parse_args()
    print args

    # Initializing Redis DB
    redis_db = redis.StrictRedis(host='localhost', port=6379, db=0)

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

    # MESSY TODO: Write an abstract class for the experiment type and implement elsewhere
    if args.experiment_type == 'REST':
        experiment_args = [args.website_ip, ip_addresses]
    elif args.experiment_type == "spark-ml-matrix":
        #website_ip in this case is the spark master public ip
        experiment_args = [args.website_ip, args.victim_machine_private_ip]
    elif args.experiment_type == "nginx-single":
        experiment_args = [args.website_ip, args.traffic_generator_public_ip]
    elif args.experiment_type == "todo-app":
        experiment_args = [args.website_ip, traffic_client]
    elif args.experiment_type == "basic-get":
        experiment_args = [args.website_ip, traffic_client]
    elif args.experiment_type == "spark-streaming":
        if not args.redis_ms:
            print 'Please enter a redis IP'
            exit()
        else:
            redis_ip = args.redis_ms
        if not args.spark_stream:
            print 'Please enter a spark-stream IP'
            exit()
        else:
            spark_stream_ip = args.spark_stream
        if not args.kafka:
            print 'Please enter a kafka IP'
            exit()
        else:
            kafka_ip = args.kafka
        if not args.spark_ms:
            print 'Please enter a spark-ms IP'
            exit()
        else:
            spark_ms_ip = args.spark_ms
        if not args.spark_wk:
            print 'Please enter the spark worker IP'
            exit()
        else:
            spark_wk_ip_list = args.spark_wk.split(',')
        redis_dict = get_container_ids_all([redis_ip], "hantaowang/redis")
        spark_stream_dict = get_container_ids_all([spark_stream_ip], "mchang6137/spark_streaming")
        kafka_dict = get_container_ids_all([kafka_ip], "mchang6137/kafka")
        spark_ms_dict = get_container_ids_all([spark_ms_ip], "mchang6137/spark-yahoo")
        spark_wk_dict = {"spark-wk": []}
        for spark_wk_ip in spark_wk_ip_list:
            spark_wk_sub_dict = get_container_ids_all([spark_wk_ip], "mchang6137/spark-yahoo")
            spark_wk_dict["spark-wk"].append(spark_wk_sub_dict["mchang6137/spark-yahoo"])
            ssh_clients[spark_wk_ip] = get_client(spark_wk_ip)
            # Adding spark worker ips to ip_addresses
            ip_addresses.append(spark_wk_ip)

        experiment_args_dict = {}
        experiment_args_dict.update(redis_dict)
        experiment_args_dict.update(spark_stream_dict)
        experiment_args_dict.update(kafka_dict)
        experiment_args_dict.update(spark_ms_dict)
        experiment_args_dict.update(spark_wk_dict)
        experiment_args = [experiment_args_dict]

        #Initialize Spark Master
        initialize_spark_experiment(experiment_args[0])
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
        print 'RESUME FUNCTIONALITY HAS BEEN SHELVED FOR LATER (AND IT IS ALSO OUTDATED)'
        exit()
        try:
            previous_results = read_from_file(args.resume, True)
        except:
            print 'File not found'
            exit()
        resume_boolean = True
    else:
        resume_boolean = False
        previous_results = None

    # Retrieving dictionary of container_ids with service names as keys
    container_ids_dict = get_container_ids(ip_addresses, services, resources, stress_policy)

    # Accounting for multi-service stressing (Currently only works for stress_policy=ALL)
    if args.multiservice_stressing:
        multi_service_lists = args.multiservice_stressing.split('|')
        for multi_service_str in multi_service_lists:
            multi_service_list = ast.literal_eval(multi_service_str)
            new_multi_service_tuple_list = []
            new_multi_service_name = None
            for multi_service in multi_service_list:
                old_container_tuple_list = container_ids_dict.pop(multi_service, None)
                if not old_container_tuple_list:
                    print 'Service {} not found'.format(multi_service)
                    exit()
                new_multi_service_tuple_list += old_container_tuple_list
                if not new_multi_service_name:
                    new_multi_service_name = multi_service
                else:
                    new_multi_service_name += '+{}'.format(multi_service)
            container_ids_dict.update({new_multi_service_name: new_multi_service_tuple_list})

    # Checking for stress search type
    if stress_policy == 'HALVING' or stress_policy == 'BINARY':
        container_ids_dict1, container_ids_dict2 = container_ids_dict

    results_disk = {}
    results_cpu = {}
    results_network = {}

    continue_stressing = True

    experiment_iteration_count = 0

    while continue_stressing:
        # Reset results dictionary for each iteration
        results_disk = {}
        results_cpu = {}
        results_network = {}

        if stress_policy == 'BINARY' or stress_policy == 'HALVING':
            results1 = model_machine(ssh_clients, container_ids_dict1, experiment_inc_args, args.iterations,
                                     args.experiment_type, stress_policy, resources,
                                     args.only_baseline, resume_boolean, previous_results, experiment_iteration_count,
                                     redis_db)
            results2 = model_machine(ssh_clients, container_ids_dict2, experiment_inc_args, args.iterations,
                                     args.experiment_type, stress_policy, resources,
                                     args.only_baseline, resume_boolean, previous_results, experiment_iteration_count,
                                     redis_db)
        else: # More will be added as more search policies are implemented
            results = model_machine(ssh_clients, container_ids_dict, experiment_inc_args, args.iterations,
                                    args.experiment_type, stress_policy, resources,
                                    args.only_baseline, resume_boolean, previous_results, experiment_iteration_count,
                                    redis_db)

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

        experiment_iteration_count += 1

    output_file_name = append_results_to_file(results_cpu, results_disk, results_network, resources, increments, args.experiment_type, args.iterations, '-',True)
    #plot_results(output_file_name, resources, args.experiment_type, args.iterations, 'save', convertToMilli=results_in_milli)
