import numpy as np
import matplotlib
matplotlib.use('Agg')

import matplotlib.pyplot as plt
import csv

input_file = csv.DictReader(open("individual_results.csv"))
print 'csv read'
variable = []

elapsedtime_list = []
perf_list = []

current_iteration = 0
current_time = 0
iteration_points = {}
iteration_min = {}
iteration_max = {}
# plot scatterplot of data
for row in input_file:
    iteration = float(row['iteration'])
    '''
    if row['iteration'] != current_iteration:
        current_iteration += 1
        current_time = row['time']
    elapsedtime_list.append(current_time)
    '''
    elapsedtime_list.append(iteration)
    if iteration not in iteration_points:
        iteration_points[iteration] = [float(row['l99'])]
        iteration_min[iteration] = [float(row['l0'])]
        iteration_max[iteration] = [float(row['l100'])]
    else:
        iteration_points[iteration].append(float(row['l99']))
        iteration_min[iteration].append(float(row['l0']))
        iteration_max[iteration].append(float(row['l100']))

    perf_list.append(row['l99'])

iteration_99 = {}
iteration_0 = {}
iteration_100 = {}
for iteration in iteration_points:
    iteration_99[iteration] = np.median(iteration_points[iteration])
    iteration_0[iteration] = np.median(iteration_min[iteration])
    iteration_100[iteration] = np.median(iteration_max[iteration])
    if iteration == 100:
        break

plot_99_list = iteration_99.values()
plot_100_list = iteration_100.values()
plot_0_list = iteration_0.values()

iterations = iteration_99.keys()

fig = plt.figure()
ax1 = fig.add_subplot(111)
ax1.scatter(iteration_0.keys(), iteration_0.values(), s=10, c='b', marker="s", label='0th')
ax1.scatter(iteration_100.keys(), iteration_100.values(), c='r', marker="o", label='100th')
ax1.scatter(iteration_99.keys(), iteration_99.values(), c='g', marker='x', label='99th')

plt.title('Scatter plot pythonspot.com')
plt.xlabel('x')
plt.ylabel('y')
#plt.show()
plt.savefig('test.png')
