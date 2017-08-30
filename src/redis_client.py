import redis_client

'''
A Throttlebot abstraction over Redis that allows Throttlebot to write experiment results and make queries to the Throttle Data store

Users of Redis should just send relevant information to the functions here, and the key names should all be generated from within this module

'''

def generate_hash_key(experiment_iteration_count, mr, perf_metric):
    resource = mr.resource
    service_name = mr.service_name
    return '{},{},{},{}'.format(experiment_iteration_count, service_name, resource, perf_metric)

def generate_ordered_performance_key(experiment_iteration_count, perf_metric, stress_percent):
    return '{},{}'.format(experiment_iteration_count, perf_metric, stress_percent)

# Writes result of the experiments to Redis for one particular MR
# Result should be a map of {Increment -> [experiment_results]}
def write_redis_results(redis_db, mr, increment_to_result, experiment_iteration_count, perf_metric):
    hash_name = generate_hash_key(experiment_iteration_count, mr, perf_metric)
    print 'Writing Results to Redis'
    print 'HashName: {}'.format(hash_name)

    for increment, experiment_results in increment_to_result:
        new_value_created = redis_db.hset(hash_name, increment, experiment_results)

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

    mr_key = generate_hash_key(experiment_iteration_count, mr, performance_metric)
    redis_db.zadd(sorted_set_name, mean_result, mr_key)

# Redis sets are ordered from lowest score to the highest score
# A metric where lower is better would have get_lowest parameter set to True
def get_top_n_mimr(redis_db, experiment_iteration_count, perf_metric, stress_weight, get_lowest=True, num_results_returned=1):
    sorted_set_name = generate_ordered_performance_key(experiment_iteration_count, perf_metric, stress_weight)
    print 'Recovering the MIMR'

    # If improving performance means lowering the performance
    # increased performnace should be the MIMR
    if !get_lowest:
        mr_score_list = redis_db.zrange(set_name, 0, num_results_returned, with_scores=True)
    else:
        num_results_returned = -1 * num_results_returned
        mr_score_list = redis_db.zrange(set_name, num_results_returned, -1, with_scores=True)
    assert mr_score_list != 0
    print 'For experiment {}, the MIMR is {}'.format(experiment_iteration_count, mr_score_list[0][0])
    print 'The entire MR, score list is: {}'.format(mr_score_list)
    return mr_score_list

# After each iteration of Throttlebot, write a summary, essentially a record of what Throttlebot did
# perf_gain should be the performance gain over the baseline
# action_taken should be the amount of performance improvement given to the MIMR  in the form of +x, where x is a raw amount added to the MR
# Currently assuming that there is only a single metric that a user would care about
def write_summary_redis(redis_db, experiment_iteration_count, mimr, perf_gain, action_taken):
    hash_name = '{}summary'.format(experiment_iteration_count)
    redis_db.hset(hash_name, 'mimr', mimr)
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
    redis_db.lpush(service_ip_key, identifier_tuple[0])
    redis_db.lpush(service_docker_key, identifier_tuple[1])

def read_service_locations(redis_db, service):
    service_ip_key = '{}_ip'.format(service)
    service_docker_key = '{}_id'.format(service)
    ip_list = redis_db.lrange(service_ip_key, 0, -1)
    docker_list = redis_db.lrange(service_docker_key, 0, -1)

    return zip(ip_list, docker_list)
