import redis.client

from mr import MR

import logging

'''
A Throttlebot abstraction over Redis that allows Throttlebot to write experiment results and make queries to the Throttle Data store

Users of Redis should just send relevant information to the functions here, and the key names should all be generated from within this module

'''

def generate_hash_key(experiment_iteration_count, mr, perf_metric):
    resource = mr.resource
    service_name = mr.service_name
    return '{},{},{},{}'.format(experiment_iteration_count, service_name, resource, perf_metric)

# Inverts the calculation done from generate_hash_key()
def generate_mr_from_hashkey(redis_db, hashkey):
    _,service_name,resource,_ = hashkey.split(',')
    deployments = read_service_locations(redis_db, service_name)
    return MR(service_name, resource, deployments)
    
def generate_ordered_performance_key(experiment_iteration_count, perf_metric, stress_percent):
    return '{},{},{}'.format(experiment_iteration_count, perf_metric, stress_percent)

# Writes result of the experiments to Redis for one particular MR
# Result should be a map of {Increment -> [experiment_results]}
def write_redis_results(redis_db, mr, increment_to_result, experiment_iteration_count, perf_metric):
    hash_name = generate_hash_key(experiment_iteration_count, mr, perf_metric)
    logging.info('Writing Results to Redis')
    logging.info('HashName: {}'.format(hash_name))

    for stress_weight in increment_to_result:
        experiment_results = increment_to_result[stress_weight][perf_metric]
        redis_db.hset(hash_name, 'num_exp_{}'.format(stress_weight), len(experiment_results))
        count = 0
        for result in experiment_results:
            exp_key = 'exp_{}_{}'.format(stress_weight, count)
            count += 1
            new_value_created = redis_db.hset(hash_name, exp_key, result)

            # This function should never be overwriting a previous value
            if new_value_created == 1:
                continue
            else:
                print('WARNING: Throttlebot should not be overwriting an old value')
                exit()

# Returns a dict of all the experiment results for a certain MR
def read_redis_result(redis_db, experiment_iteration_count, mr, perf_metric):
    print('Reading results from Redis')
    hash_name = generate_hash_key(experiment_iteration_count, mr, perf_metric)
    exp_dict = redis_db.hgetall(hash_name)
    print(exp_dict)
    exit()


# Writes scored result of the experiment to Redis
# Maps the ordered performance times to the correct MR experiment
def write_redis_ranking(redis_db, experiment_iteration_count, perf_metric, mean_result, mr, stress_weight):
    logging.info('Writing to the Redis Ranking')
    sorted_set_name = generate_ordered_performance_key(experiment_iteration_count, perf_metric, stress_weight)
    logging.info('SortedSetName: {}'.format(sorted_set_name))

    mr_key = generate_hash_key(experiment_iteration_count, mr, perf_metric)
    redis_db.zadd(sorted_set_name, {mr_key: mean_result})

# Redis sets are ordered from lowest score to the highest score
# A metric where lower is better would have get_lowest parameter set to True
def get_top_n_mimr(redis_db, experiment_iteration_count, perf_metric, stress_weight, gradient_mode, optimize_for_lowest=True, num_results_returned=-1):
    if gradient_mode == 'inverted':
        optimize_for_lowest = not optimize_for_lowest
        
    sorted_set_name = generate_ordered_performance_key(experiment_iteration_count, perf_metric, stress_weight)
    logging.info('Recovering the MIMR from {}'.format(sorted_set_name))

    # If improving performance means lowering the performance
    # increased performnace should be the MIMR
    if optimize_for_lowest is False:
        mr_score_list = redis_db.zrange(sorted_set_name, 0, num_results_returned, desc=False, withscores=True)
    else:
        mr_score_list = redis_db.zrange(sorted_set_name, 0, num_results_returned, desc=True, withscores=True)
    assert len(mr_score_list) != 0
    logging.info('For experiment {}, the MIMR is {}'.format(experiment_iteration_count, mr_score_list[0][0]))
    logging.info('The entire MR, score list is: {}'.format(mr_score_list))

    mr_object_score_list = []
    for mr_result in mr_score_list:
        mr_hash,score = mr_result
        mr = generate_mr_from_hashkey(redis_db, mr_hash)
        mr_object_score_list.append((mr, score))

    return mr_object_score_list

''' 
Store the results of the filtered experiments
'''
def generate_ordered_filter_key(filter_name, exp_iteration):
    return 'filter_{}.{}'.format(filter_name, exp_iteration)

def write_filtered_results(redis_db, filter_type, exp_iteration, repr_string, exp_result): 
    sorted_set_name = generate_ordered_filter_key(filter_type, exp_iteration) 
    #redis_db.zadd(sorted_set_name, exp_result, repr_string)
    redis_db.zadd(sorted_set_name, {repr_string: exp_result})

# Redis sets are ordered from lowest score to the highest score
# A metric where lower is better would have get_lowest parameter set to True
def get_top_n_filtered_results(redis_db,
                               filter_type,
                               exp_iteration,
                               sys_config,
                               optimize_for_lowest=True,
                               num_results_returned=-1):
    sorted_set_name = generate_ordered_filter_key(filter_type, exp_iteration)
    logging.info('Recovering the bottlenecked pipeline...')

    # If improving performance means lowering the performance
    # increased performnace should be the MIMR
    if optimize_for_lowest is False:
        pipeline_score_list = redis_db.zrange(sorted_set_name, 0,
                                              num_results_returned,
                                              desc=False, withscores=True)
    else:
        pipeline_score_list = redis_db.zrange(sorted_set_name, 0,
                                              num_results_returned,
                                              desc=True, withscores=True)

    return pipeline_score_list

'''
Summary Operations!

After each iteration of Throttlebot, write a summary, essentially a record of what Throttlebot did
perf_gain should be the performance gain over the baseline
action_taken maps a MR to the amount that it was added to or removed from
Currently assuming that there is only a single metric that a user would care about
Elapsed time is in seconds
'''

def write_summary_redis(redis_db, experiment_iteration_count, mimr, perf_gain, action_taken, analytic_perf, current_perf, current_perf_std, elapsed_time, cumm_mr, is_backtrack=False, all_results=[]):
    action_taken_str = ''
    for mr in action_taken:
        action_taken_str += 'MR {} changed by {},'.format(mr.to_string(), action_taken[mr])
    
    hash_name = '{}summary'.format(experiment_iteration_count)
    redis_db.hset(hash_name, 'mimr', mimr.to_string())
    redis_db.hset(hash_name, 'perf_improvement', perf_gain)
    redis_db.hset(hash_name, 'action_taken', action_taken_str)
    redis_db.hset(hash_name, 'current_perf', current_perf)
    redis_db.hset(hash_name, 'current_std', current_perf_std)
    redis_db.hset(hash_name, 'elapsed_time', elapsed_time)
    redis_db.hset(hash_name, 'cumulative_mr', cumm_mr)
    redis_db.hset(hash_name, 'analytic_perf', analytic_perf)
    redis_db.hset(hash_name, 'is_backtrack', int(is_backtrack))

    trial_num = 0
    for result in all_results:
        trial_str = 'trial{}_perf'.format(trial_num)
        redis_db.hset(hash_name, trial_str, result)
        trial_num += 1

    logging.info('Summary of Iteration {} written to redis'.format(experiment_iteration_count))

def read_summary_redis(redis_db, experiment_iteration_count):
    hash_name = '{}summary'.format(experiment_iteration_count)
    mimr = redis_db.hget(hash_name, 'mimr')
    perf_improvement = redis_db.hget(hash_name, 'perf_improvement')
    action_taken = redis_db.hget(hash_name, 'action_taken')
    current_perf = redis_db.hget(hash_name, 'current_perf')
    elapsed_time = redis_db.hget(hash_name, 'elapsed_time')
    cumulative_mr = redis_db.hget(hash_name, 'cumulative_mr')
    analytic_perf = redis_db.hget(hash_name, 'analytic_perf')
    is_backtrack = bool(redis_db.hget(hash_name, 'is_backtrack'))
    return mimr, action_taken, perf_improvement,analytic_perf, current_perf, elapsed_time, cumulative_mr, is_backtrack


'''
This index is a mapping of a particular service (which is assumed to be
constant for a run of Throttlebot to the (IP Address, docker container
id) of the machine that it is running on.

ASSUMPTION: Each machine instance does not have two containers with the same
service on it

'''

# identifier_tuple is a list of tuples of (IP address, docker_container_id)
# Note that we use the docker_container_id to distinguish it from the
# Quilt container id, which is different
def write_service_locations(redis_db, service, identifier_tuple):
    service_ip_key = '{}_ip'.format(service)
    service_docker_key = '{}_id'.format(service)
    for location in identifier_tuple:
        redis_db.lpush(service_ip_key, location[0])
        redis_db.lpush(service_docker_key, location[1])

def read_service_locations(redis_db, service):
    service_ip_key = '{}_ip'.format(service)
    service_docker_key = '{}_id'.format(service)
    ip_list = redis_db.lrange(service_ip_key, 0, -1)
    docker_list = redis_db.lrange(service_docker_key, 0, -1)

    return zip(ip_list, docker_list)

def delete_service_locations(redis_db, service):
    service_ip_key = '{}_ip'.format(service)
    service_docker_key = '{}_id'.format(service)
    redis_db.delete(service_ip_key)
    redis_db.delete(service_docker_key)
