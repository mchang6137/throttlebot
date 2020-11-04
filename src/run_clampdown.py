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

import logging


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

    logging.info('\n' * 2)
    logging.info('*' * 20)
    logging.info('INITIALIZING RESOURCE CONFIG')
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
                logging.info('Maxing our resources for on-prem: MR {} increase from {} to {}'.format(mr.to_string(), current_mr_alloc, new_mr_alloc))
                
    logging.info('Filled out resources for on-prem mode')

    logging.info('*' * 20)
    logging.info('INFO: INSTALLING DEPENDENCIES')
    install_dependencies(workload_config)

    # Initialize time for data charts
    time_start = datetime.datetime.now()

    logging.info('*' * 20)
    logging.info('INFO: RUNNING BASELINE')

    current_performance = measure_baseline(workload_config,
                                           baseline_trials,
                                           workload_config['include_warmup'])

    current_performance[preferred_performance_metric] = remove_outlier(current_performance[preferred_performance_metric])
    baseline_performance = current_performance[preferred_performance_metric]
    baseline_mean = mean_list(baseline_performance)
    current_time_stop = datetime.datetime.now()
    time_delta = current_time_stop - time_start

    logging.info('The Baseline performance is {}'.format(baseline_mean))
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
        logging.info('\n\n\n\n\n')
        logging.info('Cutting round number {}'.format(experiment_count))
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

        logging.info('Pipelines to consider are {}'.format(pipeline_to_consider))
        # Iterate through the pipelines and keep clamping down on the pipelines
        for pipeline in pipeline_to_consider:
            logging.info('Exploring pipeline {}'.format([mr.to_string() for mr in pipeline]))
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
                logging.warning('Failed, trying a new filtering pipeline')
            else:
                # Commit the changes
                for mr in pipeline:
                    logging.info('MR {} cut from {} to {}'.format(mr.to_string(), mr_original_allocation[mr], mr_new_allocation[mr]))
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
            logging.info('tuned_config.csv below')
            logging.info('SERVICE,RESOURCE,AMOUNT,REPR\n')
            for mr in current_mr_config:
                result_string += '{},{},{},RAW\n'.format(mr.service_name, mr.resource, current_mr_config[mr])
            result_string += '\n\n'
            logging.info(result_string)
	    myfile.write(result_string)

    print_csv_configuration(current_mr_config)

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
                logging.error('Invalid service name in [Basic] field {}'.format(service_name))
                exit()

        for resource in known_imr_resource:
            if resource not in all_resources:
                logging.error('Invalid resource name in [Basic] field {}'.format(resource))
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
            logging.error('You need to specify some services to try to fill first!')
            exit()
    else:
        sys_config['fill_services_first'] = fill_services_first.split(',')
        for service in sys_config['fill_services_first']:
            if service not in all_services:
                logging.error('Invalid service name {}. Change your field fill_services_first'.format(service))
                exit()

    # Configuration parameters relating to the filter step
    filter_config['filter_policy'] = config.get('Filter', 'filter_policy')
    assert filter_config['filter_policy'] == 'pipeline' or filter_config['filter_policy'] == 'pipeline_clampdown' or filter_config['filter_policy'] == ''
    if filter_config['filter_policy'] != 'pipeline_clampdown':
        logging.error('Are you sure the Filter policy should not be pipeline_clampdown? Exiting..')
        exit()
    
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
    workload_config['workload_num'] = config.get('Workload', 'workload_num')
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config_file", help="Configuration File for Throttlebot Execution")
    parser.add_argument("--resource_config", help='Default Resource Allocation for Throttlebot')
    parser.add_argument("--last_completed_iter", type=int, default=0, help="Last iteration completed")
    args = parser.parse_args()

    logging.getLogger().setLevel(logging.INFO)

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
        logging.info(workload_config)
        
    experiment_start = time.time()
    runClampdown(sys_config, workload_config, filter_config, mr_allocation, args.last_completed_iter)
    experiment_end = time.time()

    # Record the time and the number of MRs visited
    logging.info('The experiment runs for a total of {}'.format(experiment_end - experiment_start))
