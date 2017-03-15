from max_resource_capacity import *
from remote_execution import *

#Converts CPU throttle time from nanoseconds to seconds
def get_cpu_throttle_time(ssh_client, throttle_time, increment):
    return throttle_time / (10**9)

def get_disk_throttle_time(ssh_client, result_in_bytes, increment):
    disk_throttle = float(result_in_bytes) / get_disk_capabilities(ssh_client, increment)
    return disk_throttle

def get_network_throttle_time(ssh_client, result_in_bytes, increment):
    all_container_interface_throttled = get_network_capabilities(ssh_client, increment)
    all_container_interface_baseline = get_network_capabilities(ssh_client, 0)
    network_throttle =  float(result_in_bytes) / all_container_interface_throttled.itervalues().next() - float(result_in_bytes) / all_container_interface_baseline.itervalues().next()
    return network_throttle

def calculate_total_delay_added(results, results_diff, increment, resource_field):
    print '======================='
    print 'RESOURCE FIELD IS {}'.format(resource_field)
    print 'INCREMENT IS {}'. format(increment)
    print 'results: {}\n '.format(results)
    print 'results_diff: {}\n'.format(results_diff)
    for iteration_count in range(len(results[increment])):
        total_delay_added = 0
        if resource_field == 'CPU':
            total_delay_added += get_disk_throttle_time(ssh_client, results_diff[increment][iteration_count]['disk'], increment)
            print 'DISK ADDED IS {}'.format(total_delay_added)
    	    network_time = get_network_throttle_time(ssh_client, results_diff[increment][iteration_count]['network_outbound'], increment)
	    network_time += get_network_throttle_time(ssh_client, results_diff[increment][iteration_count]['network_inbound'], increment)
            print 'Network time added is {}'.format(network_time)
            total_delay_added += network_time
        elif resource_field == 'Disk':
            total_delay_added += get_cpu_throttle_time(ssh_client, results_diff[increment][iteration_count]['cpu'], increment)
            print 'CPU ADDED IS {}'.format(total_delay_added)
            network_time = get_network_throttle_time(ssh_client, results_diff[increment][iteration_count]['network_outbound'], increment)
            network_time  += get_network_throttle_time(ssh_client, results_diff[increment][iteration_count]['network_inbound'], increment)
            print 'Network time added is {}'.format(network_time)
            total_delay_added += network_time
	elif resource_field == 'Network':
            total_delay_added += get_cpu_throttle_time(ssh_client, results_diff[increment][iteration_count]['cpu'], increment)
            print 'CPU ADDED IS {}'.format(total_delay_added)
            disk_delay= get_disk_throttle_time(ssh_client, results_diff[increment][iteration_count]['disk'], increment)
            print 'Disk added is {}'.format(disk_delay)
            total_delay_added += disk_delay

        print 'TOTAL DELAY ADDED {} seconds'.format(total_delay_added)
        #Convert total_delay_added from seconds to milliseconds
        total_delay_added *= 1000
        results[increment][iteration_count] = results[increment][iteration_count] - total_delay_added

    print 'new results is {}'.format(results)
    print '================================='

    return results
