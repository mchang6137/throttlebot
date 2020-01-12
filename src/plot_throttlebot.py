import numpy as np
import matplotlib
matplotlib.use('Agg')

import matplotlib.pyplot as plt
import redis.client

import csv

input_file = csv.DictReader(open("individual_results.csv"))
variable = []

elapsedtime_list = []
perf_list = []

current_iteration = 0
current_time = 0
# plot scatterplot of data
for row in input_file:
    if row['iteration'] != current_iteration:
        current_iteration += 1
        current_time = row['time']
    elapsedtime_list.append(current_time)
    perf_list.append(row['performance'])

    
'''
From REDIS
redis_db = redis.StrictRedis(host='0.0.0.0', port=6379, db=0)

time_transpired = []
performance = []

num_iterations = 90
trials_per_experiment = 5
for x in range(num_iterations):
    hash_name = '{}summary'.format(x)
    elapsed_time = float(redis_db.hget(hash_name, 'elapsed_time'))
    for y in range(trials_per_experiment):
        try:
            perf = float(redis_db.hget(hash_name, 'trial{}_perf'.format(y)))
            performance.append(perf)
            time_transpired.append(elapsed_time)
        except:
            continue
'''


plt.scatter(elapsedtime_list, perf_list)
plt.title('Scatter plot pythonspot.com')
plt.xlabel('x')
plt.ylabel('y')
plt.savefig('test.png')
