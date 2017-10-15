import matplotlib.pyplot as plt
from string import maketrans
from ast import literal_eval
import numpy as np
import os

import redis_client as tbot_datastore


'''
Get charts of the results of the experiments
'''
def get_summary_mimr_charts(redis_db, workload_config, baseline_perf, mr_to_stress, experiment_iteration_count, stress_weights, preferred_performance_metric, time_id):
    max_stress = min(stress_weights)
    width = 0.8
    indices = np.arange(experiment_iteration_count + 1)
    chart_directory = 'results/graphs/{}/'.format(workload_config['type'] + str(time_id))
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
                result_dict = tbot_datastore.read_redis_result(redis_db, iteration, mr, preferred_performance_metric)
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


def get_summary_performance_charts(redis_db, workload_config, experiment_iteration_count, time_id):
    # Creating general performance chart
    chart_directory = 'results/graphs/{}/'.format(workload_config['type'] + str(time_id))
    experiment_type = workload_config['type']
    get_performance_over_time_chart(redis_db, experiment_type, experiment_iteration_count, chart_directory)
    get_performance_over_mr_chart(redis_db, experiment_type, experiment_iteration_count, chart_directory)


def get_performance_over_time_chart(redis_db, experiment_type, experiment_iteration_count, chart_directory):
    # Creating performance over time chart
    x = []
    y = []
    for iteration in range(experiment_iteration_count + 1):
        _, _, _,_, curr_perf, elaps_time, _ = tbot_datastore.read_summary_redis(redis_db, iteration)
        x.append(elaps_time)
        y.append(curr_perf)
    plt.plot(x, y, drawstyle='steps-post')
    plt.title('{} Performance Over Time'.format(experiment_type))
    plt.xlabel('Elapsed Time (seconds)')
    plt.ylabel('Latency_99 (ms)')
    chart_name = '{}{}{}performance_time.png'.format(chart_directory, experiment_iteration_count, experiment_type)
    plt.savefig(chart_name)
    plt.clf()


def get_performance_over_mr_chart(redis_db, experiment_type, experiment_iteration_count, chart_directory):
    x = []
    y = []
    for iteration in range(experiment_iteration_count + 1):
        _, _, _, _,curr_perf, _, cumulative_mr = tbot_datastore.read_summary_redis(redis_db, iteration)
        x.append(cumulative_mr)
        y.append(curr_perf)
    plt.plot(x, y, drawstyle='steps-post')
    plt.title('{} Performance Over Number of MRs Stressed'.format(experiment_type))
    plt.xlabel('Number of MRs Stressed')
    plt.ylabel('Latency_99 (ms)')
    chart_name = '{}{}{}performance_mr.png'.format(chart_directory, experiment_iteration_count, experiment_type)
    plt.savefig(chart_name)
    plt.clf()

# Temporary Main function for testing
if __name__ == "__main__":
    pass
