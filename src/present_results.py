import matplotlib.pyplot as plt
import ast
import numpy
import argparse
import csv
import datetime
import os

from remote_execution import *
from matplotlib.backends.backend_pdf import PdfPages

def read_from_file(data_file, resume_boolean):
    cpu = {}
    disk = {}
    network = {}

    with open(data_file) as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            service = row['service']
            metric = row['metric']
            stress_level = row['increment']
            resource = row['resource']
            results = row['data_points']

            if service not in cpu:
                cpu[service] = {}
                disk[service] = {}
                network[service] = {}

            # Accounting for the swapped metric/increment
            # ALL RESUME ARE OUTDATED
            if resume_boolean:
                stress_level = int(stress_level)
                if stress_level not in cpu[service]:
                    cpu[service][stress_level] = {}
                    disk[service][stress_level] = {}
                    network[service][stress_level] = {}

                int_list_results = [float(numb) for numb in results[1:-1].split(',')]

                if resource == 'cpu':
                    cpu[service][stress_level][metric] = int_list_results
                elif resource == 'disk':
                    disk[service][stress_level][metric] = int_list_results
                elif resource == 'network':
                    network[service][stress_level][metric] = int_list_results
            else:
                if metric not in cpu[service]:
                    cpu[service][metric] = {}
                    disk[service][metric] = {}
                    network[service][metric] = {}

                if resource == 'cpu':
                    cpu[service][metric][stress_level] = results
                elif resource == 'disk':
                    disk[service][metric][stress_level] = results
                elif resource == 'network':
                    network[service][metric][stress_level] = results

    return cpu, disk, network

def plot_boxplot(axis_labels, box_array, metric, resource_field, subplot_number, use_causal_analysis, ylim_min, ylim_max):
    axis_labels.sort()
    axis_labels = [str(x) for x in axis_labels]
    print axis_labels
    plt.xticks([1,2,3,4,5], axis_labels)
    # plt.subplot(subplot_number)
    plt.ylabel('Metric: {}'.format(metric))
    plt.ylim([ylim_min, ylim_max])
    plt.xlabel('Stress Percentage')
    if use_causal_analysis:
        plt.title('Stressing all resources except {}'.format(resource_field))
    else:
        plt.title('Stressing only {}'.format(resource_field))
    plt.boxplot(box_array)
    plt.grid(True)

# OUTDATED NO CONTAINER
def plot_interpolation(box_array, metric, resource, experiment_type='changeme!', service='changeme!', container_id='changeme!'):
    median_box = [numpy.median(increment_result) for increment_result in box_array]
    x = [0, 20, 40, 60, 80]
    # x = [0, 50] # TESTING
    std_dev = [numpy.std(increment_result) for increment_result in box_array]
    plt.xlim(-5, 85)
    font = {'family':'serif','serif':['Times']}
    if len(service) < 15:
        plt.title('Exp: \"{}\" Service: \"{}...\" Container: \"{}\"'.format(experiment_type, service, container_id), fontname="Times New Roman", size=18)
    else:
        plt.title('Exp: \"{}\" Service: \"{}...\" Container: \"{}\"'.format(experiment_type, service[:15], container_id), fontname="Times New Roman", size=18)
    plt.ylabel('{} (ms)'.format(metric), fontname="Times New Roman", size=16)
    plt.xlabel('Percentage Resource Stressed', fontname="Times New Roman", size=16)
    if resource == 'CPU':
        line_color = '#990000'
        error_length = 1
    elif resource == 'Disk':
        line_color = 'black'
        error_length = 1.5
    elif resource == 'Network':
        line_color = '#999999'
        error_length = 2
    line, = plt.plot(x, median_box, lw=3, label=resource, color=line_color)
    # plt.legend(handles=[line])
    plt.errorbar(x, median_box, std_dev, lw=error_length, color=line_color)
    return line

def plot_flat_baseline(box_array, metric):
    print box_array
    median = numpy.median(box_array[0])
    x = [-5, 20, 40, 60, 85]
    flat_line = [median] * 5
    plt.plot(x, flat_line, 'r--', label='Baseline (No stresses)')

def append_results_to_file(cpu, disk, network, resources, increments, experiment_type, use_causal_analysis, iterations,
                           experiment_iteration_count, finished_boolean):
    OUTPUT_DIRECTORY = 'results/'
    causal_output = ''
    if use_causal_analysis:
        causal_output = 'causal'
    else:
        causal_output = 'singlestress'

    if finished_boolean:
        status = 'Full'
    else:
        status = 'Checkpoint'

    output_file_name = '{}_{}_{}_{}_{}.csv'.format(status, experiment_type, causal_output, experiment_iteration_count,
                                                   datetime.datetime.now())

    if not os.path.exists(OUTPUT_DIRECTORY):
        os.makedirs(OUTPUT_DIRECTORY)

    with open(OUTPUT_DIRECTORY + output_file_name, 'wb') as csvfile:
        fieldnames = ['service', 'metric', 'increment', 'resource', 'mean', 'stddev', 'data_points']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        # Checking for used resource
        base = None
        if 'CPU' in resources:
            base = cpu
        elif 'NET' in resources:
            base = network
        elif 'DISK' in resources:
            base = disk

        for service, data in base.iteritems():
            all_metric_keys = data[min(increments)].keys()
            for metric in all_metric_keys:
                for increment_key in sorted(data.iterkeys()):
                #Iterate through different metrics
                    if 'CPU' in resources:
                        results_cpu = cpu[service][increment_key][metric]
                        writer.writerow({'service': service, 'metric': metric,
                                         'increment': increment_key, 'resource': 'cpu',
                                         'mean': numpy.mean(results_cpu), 'stddev': numpy.std(results_cpu),
                                         'data_points': results_cpu})
                    if 'DISK' in resources:
                        results_disk = disk[service][increment_key][metric]
                        writer.writerow({'service': service, 'metric': metric,
                                         'increment': increment_key, 'resource': 'disk',
                                         'mean': numpy.mean(results_disk), 'stddev': numpy.std(results_disk),
                                         'data_points': results_disk})
                    if 'NET' in resources:
                        results_network = network[service][increment_key][metric]
                        writer.writerow({'service': service, 'metric': metric,
                                         'increment': increment_key, 'resource': 'network',
                                         'mean': numpy.mean(results_network), 'stddev': numpy.std(results_network),
                                         'data_points': results_network})

    return OUTPUT_DIRECTORY + output_file_name

# OUTDATED (NO CONTAINER ID)
def plot_results(data_file, resources, experiment_type, iterations, should_save, convertToMilli=True, use_causal_analysis=True):
    cpu, disk, network = read_from_file(data_file, False)

    OUTPUT_DIRECTORY = 'results/graphs/'
    causal_output = ''
    if use_causal_analysis:
        causal_output = 'causal'
    else:
        causal_output = 'singlestress'
    output_dir_name = '{}_{}_{}_{}'.format(experiment_type, causal_output, iterations, datetime.datetime.now())

    # Save the image in the appropriate directory
    if not os.path.exists(OUTPUT_DIRECTORY + output_dir_name):
        os.makedirs(OUTPUT_DIRECTORY + output_dir_name)

    # Checking for used resource
    base = None
    if 'CPU' in resources:
        base = cpu
    elif 'NET' in resources:
        base = network
    elif 'DISK' in resources:
        base = disk

    for service, containerd in base.iteritems():
        for container, data in containerd.iteritems():
            for metric in data.iterkeys():

                fig = plt.figure(1, figsize=(11,6))
                ax = fig.add_subplot(111)

                box_array_cpu = []
                box_array_disk = []
                box_array_network = []
                axis_labels = []

                baseline_results = numpy.mean(ast.literal_eval(data[metric]['0']))
                print 'baseline results is {}'.format(baseline_results)

                for increment_key in sorted(data[metric].iterkeys()):
                    # Iterate through different metrics
                    if 'CPU' in resources:
                        results_cpu = ast.literal_eval(cpu[service][container][metric][increment_key])
                    if 'DISK' in resources:
                        results_disk = ast.literal_eval(disk[service][container][metric][increment_key])
                    if 'NET' in resources:
                        results_network = ast.literal_eval(network[service][container][metric][increment_key])

                    # results_cpu = [result - baseline_results for result in results_cpu]
                    # results_disk = [result - baseline_results for result in results_disk]
                    # results_network = [result - baseline_results for result in results_network]

                    print '==========================================================='
                    print 'FOR CONTAINER {} OF SERVICE {}'.format(container, service)
                    print 'THE METRIC IS: {}'.format(metric)
                    print 'For Key: {}'.format(increment_key)
                    if 'CPU' in resources:
                        print 'CPU stats:'
                        print 'Mean: {}'.format(numpy.mean(results_cpu))
                        print 'Standard Deviation: {}\n'.format(numpy.std(results_cpu))

                    if 'DISK' in resources:
                        print 'Disk Stats: '
                        print 'Mean: {}'.format(numpy.mean(results_disk))
                        print 'Standard Deviation: {}\n'.format(numpy.std(results_disk))

                    if 'NET' in resources:
                        print 'Network Stats: '
                        print 'Mean: {}'.format(numpy.mean(results_network))
                        print 'Standard Deviation: {}\n'.format(numpy.std(results_network))

                    axis_labels.append(increment_key)
                    if 'CPU' in resources:
                        try:
                            temp_array_cpu = numpy.array(results_cpu)
                            # no_outliers_cpu = temp_array_cpu[~is_outlier(results_cpu)]
                            box_array_cpu.append(temp_array_cpu)
                        except:
                            print 'CPU FAILED'

                    if 'DISK' in resources:
                        try:
                            temp_array_disk = numpy.array(results_disk)
                            # no_outliers_disk = temp_array_disk[~is_outlier(results_disk)]
                            box_array_disk.append(temp_array_disk)
                        except:
                            print 'DISK FAILED'

                    if 'NET' in resources:
                        try:
                            temp_array_network = numpy.array(results_network)
                            # no_outliers_network = temp_array_network[~is_outlier(results_network)]
                            box_array_network.append(temp_array_network)
                        except:
                            print 'NETWORK FAILED'

                # ymin = 1.05 * min(find_min_point(box_array_cpu), find_min_point(box_array_disk), find_min_point(box_array_network))
                # ymax = 1.2 * max(find_max_point(box_array_cpu), find_max_point(box_array_disk), find_max_point(box_array_network))

                # Plots the boxplots
                # plot_boxplot(axis_labels, box_array_disk, metric, 'Disk', 222, use_causal_analysis, ymin, ymax)
                # plot_boxplot(axis_labels, box_array_network, metric, 'Network', 221, use_causal_analysis, ymin, ymax)
                # plot_boxplot(axis_labels, box_array_cpu, metric, 'CPU', 223, use_causal_analysis, ymin, ymax)

                # Plots through the medians
                if 'DISK' in resources:
                    plot_interpolation(box_array_disk, metric, 'Disk', experiment_type, service, container)
                if 'NET' in resources:
                    plot_interpolation(box_array_network, metric, 'Network', experiment_type, service, container)
                if 'CPU' in resources:
                    plot_interpolation(box_array_cpu, metric, 'CPU', experiment_type, service, container)

                if 'DISK' in resources:
                    plot_flat_baseline(box_array_disk, metric)
                elif 'NET' in resources:
                    plot_flat_baseline(box_array_network, metric)
                elif 'DISK' in resources:
                    plot_flat_baseline(box_array_cpu, metric)

                plt.legend(loc=(0.05, 0.6))
                plt.grid()

                graph_file = OUTPUT_DIRECTORY + output_dir_name + '/' + container + metric + '.png'
                # graph_file = './' + output_dir_name +  metric + '.png'

                print output_dir_name
                if should_save == 'save_pdf':
                    pp = PdfPages(output_dir_name + '.pdf')
                    pp.savefig()
                    pp.close()
                plt.savefig(graph_file)
                plt.show()

    return

def find_min_point(results):
    min_val = float("inf")
    for increment in results:
        if min_val > numpy.amin(increment):
            min_val = numpy.amin(increment)

    return min_val

def find_max_point(results):
    max_val = -1 * float("inf")
    for increment in results:
        if max_val < numpy.amax(increment):
            max_val = numpy.amax(increment)

    return max_val


# Temporary Main function for testing
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output_file", help="File containing results" )
    parser.add_argument("resources_to_stress", help="List of resources to throttle")
    args = parser.parse_args()
    print args
    results_in_milli = False

    plot_results(args.output_file, args.resources_to_stress.split(','), 'todo-app', 1, 'save', False, False)
