import redis_client

'''
A Throttlebot abstraction over Redis that allows Throttlebot to write experiment results and make queries to the Throttle Data store

Users of Redis should just send relevant information to the functions here, and the key names should all be generated from within this module

'''

def generate_hash_key(experiment_iteration_count, mr, perf_metric):
    resource = mr.resource
    service_name = mr.service_name
    return '{},{},{},{}'.format(experiment_iteration_count, service_name, resource, perf_metric)

def generate_ordered_performance_key(experiment_iteration_count, perf_metric):
    return '{},{}'.format(experiment_iteration_count, perf_metric)

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
def write_redis_ranking(redis_db, experiment_iteration_count, perf_metric, mean_result, mr):
    print 'Writing to the Redis Ranking'
    sorted_set_name = generate_ordered_performance_key(experiment_iteration_count, perf_metric)
    print 'SortedSetName: {}'.format(sorted_set_name)

    mr_key = generate_hash_key(experiment_iteration_count, mr, performance_metric)
    redis_db.zadd(sorted_set_name, mean_result, mr_key)

# Redis sets are ordered from lowest score to the highest score
# A metric where lower is better would have get_lowest parameter set to True
def get_mimr(redis_db, experiment_iteration_count, perf_metric, get_lowest=True):
    set_name = '{},{}'.format(experiment_iteration_count, perf_metric)
    print 'Recovering the MIMR'
    if get_lowest:
        mr, score = redis_db.zrange(set_name, 0, 0, with_scores=True)
    else:
        mr, score = redis_db.zrange(set_name, -1, -1, with_scores=True)
    print 'For experiment {}, the MIMR is {}'.format(experiment_iteration_count, mr)
    return mr,score

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
