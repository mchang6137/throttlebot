import redis.client
import matplotlib.pyplot as plt
from string import maketrans
from ast import literal_eval
import numpy as np
import datetime, os

from mr import MR

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
    print 'Writing Results to Redis'
    print 'HashName: {}'.format(hash_name)

    for stress_weight in increment_to_result:
        experiment_results = increment_to_result[stress_weight][perf_metric]
        new_value_created = redis_db.hset(hash_name, stress_weight, experiment_results)

        # This function should never be overwriting a previous value
        if new_value_created == 1:
            continue
        else:
            print 'WARNING: Throttlebot should not be overwriting an old value'

# Returns a dict of all the experiment results for a certain MR
def read_redis_result(redis_db, experiment_iteration_count, mr, perf_metric):
    print 'Reading results from Redis'
    hash_name = generate_hash_key(experiment_iteration_count, mr, perf_metric)
    return redis_db.hgetall(hash_name)

# Writes scored result of the experiment to Redis
# Maps the ordered performance times to the correct MR experiment
def write_redis_ranking(redis_db, experiment_iteration_count, perf_metric, mean_result, mr, stress_weight):
    print 'Writing to the Redis Ranking'
    sorted_set_name = generate_ordered_performance_key(experiment_iteration_count, perf_metric, stress_weight)
    print 'SortedSetName: {}'.format(sorted_set_name)

    mr_key = generate_hash_key(experiment_iteration_count, mr, perf_metric)
    redis_db.zadd(sorted_set_name, mean_result, mr_key)

# Redis sets are ordered from lowest score to the highest score
# A metric where lower is better would have get_lowest parameter set to True
def get_top_n_mimr(redis_db, experiment_iteration_count, perf_metric, stress_weight, optimize_for_lowest=True, num_results_returned=1):
    sorted_set_name = generate_ordered_performance_key(experiment_iteration_count, perf_metric, stress_weight)
    print 'Recovering the MIMR from ', sorted_set_name

    # If improving performance means lowering the performance
    # increased performnace should be the MIMR
    if optimize_for_lowest is False:
        mr_score_list = redis_db.zrange(sorted_set_name, 0, num_results_returned, desc=False, withscores=True)
    else:
        mr_score_list = redis_db.zrange(sorted_set_name, 0, num_results_returned, desc=True, withscores=True)
    assert len(mr_score_list) != 0
    print 'For experiment {}, the MIMR is {}'.format(experiment_iteration_count, mr_score_list[0][0])
    print 'The entire MR, score list is: {}'.format(mr_score_list)

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
    redis_db.zadd(sorted_set_name, exp_result, repr_string)

# Redis sets are ordered from lowest score to the highest score
# A metric where lower is better would have get_lowest parameter set to True
def get_top_n_filtered_results(redis_db,
                               filter_type,
                               exp_iteration,
                               optimize_for_lowest=True,
                               num_results_returned=0):
    sorted_set_name = generate_ordered_filter_key(filter_type, exp_iteration)
    print 'INFO: Recovering the bottlenecked pipeline...'

    # If improving performance means lowering the performance
    # increased performnace should be the MIMR
    if optimize_for_lowest is False:
        pipeline_score_list = redis_db.zrange(sorted_set_name, 0, num_results_returned, desc=False, withscores=True)
    else:
        pipeline_score_list = redis_db.zrange(sorted_set_name, 0, num_results_returned, desc=True, withscores=True)

    return pipeline_score_list

'''
Get charts of the results of the experiments
'''
def get_summary_mimr_charts(redis_db, workload_config, baseline_perf, mr_to_stress, experiment_iteration_count, stress_weights, preferred_performance_metric, time_id):
    max_stress = min(stress_weights)
    width = 0.8
    indices = np.arange(experiment_iteration_count + 1)
    chart_directory = 'results/graphs/{}/'.format(workload_config['type'] + time_id)
    # Save the image in the appropriate directory
    if not os.path.exists(chart_directory):
        os.makedirs(chart_directory)

    baseline = baseline_perf[preferred_performance_metric]
    baseline_result = float(sum(baseline)) / len(baseline)

    baseline_results = [baseline_result for _ in range(experiment_iteration_count + 1)]

    for mr in mr_to_stress:
        experiment_results = []
        for iteration in range(experiment_iteration_count + 1):
            try:
                result_dict = read_redis_result(redis_db, iteration, mr, preferred_performance_metric)
                exp_results = literal_eval(result_dict[str(max_stress)])
                experiment_results.append(float(sum(exp_results)) / len(exp_results))
            except:
                experiment_results.append(0)

        plt.bar(indices, experiment_results, width=width, color='b', label='Max Stress {} Performance'.format(max_stress))
        plt.bar(indices, baseline_results, width=0.5*width, color='r', alpha=0.5, label='Baseline Performance')
        plt.xticks(indices, [i for i in range(experiment_iteration_count + 1)])
        plt.legend()
        plt.title('{} Performance under Stress'.format(mr.to_string()))
        plt.xlabel('Experiment #')
        plt.ylabel('Latency_99 (ms)')
        chart_name = '{}{}{}.png'.format(chart_directory, iteration, mr.to_string().translate(maketrans('/', '_')))
        plt.savefig(chart_name, bbox_inches='tight')
        plt.clf()

'''
Summary Operations!

After each iteration of Throttlebot, write a summary, essentially a record of what Throttlebot did
perf_gain should be the performance gain over the baseline
action_taken should be the amount of performance improvement given to the MIMR  in the form of +x, where x is a raw amount added to the MR
Currently assuming that there is only a single metric that a user would care about
'''

def write_summary_redis(redis_db, experiment_iteration_count, mimr, perf_gain, action_taken):
    hash_name = '{}summary'.format(experiment_iteration_count)
    redis_db.hset(hash_name, 'mimr', mimr.to_string())
    redis_db.hset(hash_name, 'perf_improvement', perf_gain)
    redis_db.hset(hash_name, 'action_taken', action_taken)
    print 'Summary of Iteration {} written to redis'.format(experiment_iteration_count)

def read_summary_redis(redis_db, experiment_iteration_count):
    hash_name = '{}summary'.format(experiment_iteration_count)
    mimr = redis_db.hget(hash_name, 'mimr')
    perf_improvement = redis_db.hget(hash_name, 'perf_improvement')
    action_taken = redis_db.hget(hash_name, 'action_taken')
    return mimr, action_taken, perf_improvement

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
