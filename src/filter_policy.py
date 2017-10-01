'''
Preprocessing Step of Throttlebot
Returns a list of the MRs that should be stressed as filtering
'''
import redis_client as tbot_datastore
import redis_resource as resource_datastore
import modify_resources as resource_modifier

from run_experiment import *
from weighting_conversions import *
from mr import MR

'''
Filter Policy descriptions
pipeline: Stress all the resources being described in a pipeline
None: Apply no filter policies
'''
def apply_filtering_policy(redis_db,
                           mr_working_set,
                           experiment_iteration,
                           workload_config,
                           filter_config):
    filter_policy = filter_config['filter_policy']
    if filter_policy == 'pipeline':
        return apply_pipeline_filter(redis_db,
                                     mr_working_set,
                                     experiment_iteration,
                                     workload_config,
                                     filter_config)
    elif filter_policy is None:
        return mr_working_set

'''
A pipeline is defined as some group of services
All the resources that are part of that group of services are stressed
filter_params should be expressed as a list of lists, where each list is 
a set of services that are deemed to be part of the same pipeline
'''
def apply_pipeline_filter(redis_db,
                          mr_working_set,
                          experiment_iteration,
                          workload_config,
                          filter_config):

    print '*' * 20
    print 'INFO: Applying Filtering Pipeline'
    
    stress_weight = filter_config['stress_amount']
    experiment_trials = filter_config['filter_exp_trials']
    pipelined_services = filter_config['pipeline_services']

    # No specified pipelined services indicates that each pipeline is a service
    if pipelined_services is None:
        pipelined_services = [mr.service_name for mr in mr_working_set]
        print 'step 1: {}'.format(pipelined_services)
        pipelined_services = list(set(pipelined_services))
        print 'step 2: {}'.format(pipelined_services)
    else:
        print 'not none'
        
    tbot_metric = workload_config['tbot_metric']
    optimize_for_lowest = workload_config['optimize_for_lowest']

    for services in pipelined_services:
        print 'Mr working set is {}'.format(mr_working_set)
        print services
        mr_list = search_mr_working_set(mr_working_set, services)
        
        # Simultaneously stress the MRs in a pipeline
        for mr in mr_list:
            current_mr_allocation = resource_datastore.read_mr_alloc(redis_db, mr)
            stress_alloc = convert_percent_to_raw(mr, current_mr_allocation, stress_weight)
            resource_modifier.set_mr_provision(mr, stress_alloc)

        experiment_results = measure_runtime(workload_config, experiment_trials)
        exp_mean = mean_list(experiment_results[tbot_metric])
        repr_str = gen_pipeline_redis_repr(mr_list)
        tbot_datastore.write_filtered_results(redis_db,
                                              'pipeline',
                                             experiment_iteration,
                                             repr_str,
                                             exp_mean)

        # Revert the stressing
        for mr in mr_list:
            current_mr_allocation = resource_datastore.read_mr_alloc(redis_db, mr)
            new_alloc = convert_percent_to_raw(mr, current_mr_allocation, 0)
            resource_modifier.set_mr_provision(mr, new_alloc)

    pipeline_score_list = tbot_datastore.get_top_n_filtered_results(redis_db,
                                                                    'pipeline',
                                                                    experiment_iteration,
                                                                    optimize_for_lowest)
    print 'INFO: The current pipeline score list is here {}'.format(pipeline_score_list)
    service_names = []
    for pipeline_score in pipeline_score_list:
        pipeline_repr,score = pipeline_score
        service_names.append(parse_pipeline_redis_repr(pipeline_repr))

    local_working_set = []
    for mr in mr_working_set:
        if mr.service_name in service_names:
            local_working_set.append(mr)

    return local_working_set
            
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

# Filter down the current mr working set (list of MRs)
# on the basis of services
def search_mr_working_set(mr_working_set, services):
    result_list = []
    for mr in mr_working_set:
        if mr.service_name in services:
            result_list.append(mr)

    return result_list
            
        
        

    
    

    

