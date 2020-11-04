'''
Preprocessing Step of Throttlebot
Returns a list of the MRs that should be stressed as filtering
'''
import redis_client as tbot_datastore
import redis_resource as resource_datastore
import modify_resources as resource_modifier
import random

from mr_gradient import *
from run_experiment import *
from weighting_conversions import *
from run_throttlebot import *
from mr import MR

import logging

FILTER_LOGS = 'filter_logs.txt'

'''
Filter Policy descriptions
pipeline: Stress all the resources being described in a pipeline
None: Apply no filter policies
'''
def apply_filtering_policy(redis_db,
                           mr_working_set,
                           experiment_iteration,
                           system_config,
                           workload_config,
                           filter_config,
                           current_performance=-1):
    filter_policy = filter_config['filter_policy']
    optimize_for_lowest = workload_config['optimize_for_lowest']
    metric = workload_config['tbot_metric']
    error_tolerance = system_config['error_tolerance']
    
    if filter_policy is None:
        return mr_working_set
    
    pipeline_score_list,pipeline_groups = apply_pipeline_filter(redis_db,
                                                                mr_working_set,
                                                                experiment_iteration,
                                                                system_config,
                                                                workload_config,
                                                                filter_config)
    mr_of_interest = []
    # Just pick the most impacted pipeline (MIP)
    if filter_policy == 'pipeline':
        pipeline_repr,score = pipeline_score_list[0]
        mr_of_interest = pipeline_groups[int(pipeline_repr)]
    # Return all pipelines that are unaffected by overprovisioning
    if filter_policy == 'pipeline_clampdown':
        assert current_performance != -1
        for pipeline_score in pipeline_score_list:
            pipeline_repr, pipeline_perf = pipeline_score
            pipeline_mr = pipeline_groups[int(pipeline_repr)]
            current_performance_mean = mean_list(current_performance[metric])
            is_constant_perf = is_performance_constant(current_performance_mean, pipeline_perf, error_tolerance)
            is_improved_perf = is_performance_improved(current_performance_mean, pipeline_perf,
                                                       optimize_for_lowest, error_tolerance)
            logging.info('For pipeline {}, the current mean is {} and new performance is {}'.format([mr.to_string() for mr in pipeline_mr], current_performance_mean, pipeline_perf))
            if is_constant_perf or is_improved_perf:
                mr_of_interest.append(pipeline_mr)

    return mr_of_interest

'''
A pipeline is defined as some group of services
All the resources that are part of that group of services are stressed
filter_params should be expressed as a list of lists, where each list is 
a set of services that are deemed to be part of the same pipeline

Returns a ranked pipeline order
'''
def apply_pipeline_filter(redis_db,
                          mr_working_set,
                          experiment_iteration,
                          system_config,
                          workload_config,
                          filter_config):

    logging.info('*' * 20)
    logging.info('Applying Filtering Pipeline')

    logging.info('Filter config is {}'.format(filter_config))
    logging.info('MR working set is {}'.format(mr_working_set))
    
    machine_type = system_config['machine_type']

    pipeline_partitions = filter_config['pipeline_partitions']
    stress_weight = filter_config['stress_amount']
    experiment_trials = filter_config['filter_exp_trials']
    pipelined_services = filter_config['pipeline_services']

    pipeline_groups = []

    logging.info('Pipelined services are {}'.format(pipelined_services))
    # No specified pipelined services indicates that each pipeline is a service
    if pipelined_services[0][0] == 'BY_SERVICE':
        service_names = list(set([mr.service_name for mr in mr_working_set]))
        for service_name in service_names:
            mr_list = search_mr_working_set(mr_working_set, services)
            pipeline_groups.append(mr_list)
    elif pipelined_services[0][0] == 'RANDOM':
        pipeline_groups = gen_mr_random_split(mr_working_set, pipeline_partitions)

    logging.info("The pipeline groups are being printed below: ")
    for pipeline_group in pipeline_groups:
        pipeline_group = [mr.to_string() for mr in pipeline_group]
        logging.info('A pipeline is {}'.format(pipeline_group))
        
    tbot_metric = workload_config['tbot_metric']
    optimize_for_lowest = workload_config['optimize_for_lowest']

    pipeline_index = 0
    for pipeline in pipeline_groups:
        change_mr_schedule = calculate_mr_gradient_schedule(redis_db,
                                                            pipeline,
                                                            system_config,
                                                            stress_weight)
        # Simultaneously stress the MRs in a pipeline
        for mr in change_mr_schedule:
            resource_modifier.set_mr_provision(mr, change_mr_schedule[mr], workload_config, redis_db)

        experiment_results = measure_runtime(workload_config, experiment_trials)
        exp_mean = mean_list(experiment_results[tbot_metric])
        repr_str = str(pipeline_index)
        tbot_datastore.write_filtered_results(redis_db,
                                              'pipeline',
                                              experiment_iteration,
                                              repr_str,
                                              exp_mean)

        # Revert the stressing
        change_mr_schedule = revert_mr_gradient_schedule(redis_db,
                                                         pipeline,
                                                         system_config,
                                                         stress_weight)
        for mr in change_mr_schedule:
            resource_modifier.set_mr_provision(mr, change_mr_schedule[mr], workload_config, redis_db)

        pipeline_index += 1

    all_pipeline_score_list = tbot_datastore.get_top_n_filtered_results(redis_db,
                                                                        'pipeline',
                                                                        experiment_iteration,
                                                                        system_config,
                                                                        optimize_for_lowest=optimize_for_lowest)

    return all_pipeline_score_list, pipeline_groups

# Logs the Most impacted Pipeline
def write_log_results(pipeline):
    # Log results of the filtering
    with open(FILTER_LOGS, "a") as myfile:
        # First output the result
        filter_str = '{},'.format(experiment_iteration)
        for mr in pipeline:
            filter_str += '{},'.format(mr.to_string())
        filter_str += '\n\n'
        myfile.write(filter_str)

# Find a random partition of MRs from the working set
# Splits describes the number of partitions that you are seeking to split into
# Returns a list of MRs to stress
def gen_mr_random_split(mr_working_set, splits):
    # Shuffle the working set
    random.shuffle(mr_working_set)
    # Split the list evenly and return
    return split_list_evenly(mr_working_set, splits)

def split_list_evenly(mr_working_set, splits):
    avg = len(mr_working_set) / float(splits)
    out = []
    last = 0.0

    while last < len(mr_working_set):
        out.append(mr_working_set[int(last):int(last + avg)])
        last += avg

    return out

def gen_pipeline_redis_repr(mr_list):
    services_seen = []
    for mr in mr_list:
        if mr.service_name not in services_seen:
            services_seen.append(mr.service_name)
    return ','.join(services_seen)

def parse_pipeline_redis_repr(str_repr):
    return str_repr.split(',')[0]

'''
Utilities - helper methods
'''

def mean_list(target_list):
    return sum(target_list)  / float(len(target_list))

def is_performance_constant(initial_perf, after_perf, within_x=0):
    if abs(initial_perf - after_perf) < initial_perf * within_x:
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

# Filter down the current mr working set (list of MRs)
# on the basis of services
def search_mr_working_set(mr_working_set, services):
    result_list = []
    for mr in mr_working_set:
        if mr.service_name in services:
            result_list.append(mr)

    return result_list
            
        
        

    
    

    

