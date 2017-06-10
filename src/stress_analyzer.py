import argparse
from remote_execution import *

### Functions below are for getting initial container dictionaries

# Function that calls on the correct get_container function based on TYPE
def get_container_ids(vm_ips, services, stress_type):
    if stress_type == 'ALL':
        return get_container_ids_all(vm_ips, services)
    elif stress_type == 'BINARY':
        return get_container_ids_binary(vm_ips, services)


# Returns a dictionary of the services and their respective container_ids
# VM_IPS is a list of ip addresses, and SERVICES is a list of services
def get_container_ids_all(vm_ips, services):
    container_id_dict = {}
    for vm_ip in vm_ips:
        ssh_client = quilt_ssh(vm_ip)
        docker_container_id = 'docker ps | tr -s \' \' | cut -d \' \' -f1 | tail -n +2'
        docker_container_cmd = 'docker ps --no-trunc | grep -oP \'\"\K[^\"]+(?=[\"])\''
        _, stdout1, _ = ssh_client.exec_command(docker_container_id)
        container_ids = stdout1.read().splitlines()
        _, stdout2, _ = ssh_client.exec_command(docker_container_cmd)
        container_commands = stdout2.read().splitlines()
        for i in range(len(container_ids)):
            if services == '*' or (container_commands[i] in services):
                container_id_dict[container_commands[i]] = (vm_ip, container_ids[i])

    return container_id_dict


# Returns a tuple of dictionaries of the services and respective container_ids
# The first dictionary holds the containers to be Stressed
def get_container_ids_binary(vm_ips, services):
    container_id_dict = get_container_ids_all(vm_ips, services)
    stress_dict1 = dict(container_id_dict.items()[len(container_id_dict)/2:])
    stress_dict2 = dict(container_id_dict.items()[:len(container_id_dict)/2])

    return stress_dict1,stress_dict2


### Functions below are for updating container dictionaries

# Returns an updated dictionary of the containers to stress based on type
# OLD_CONTAINERS is the previous dictionary of containers, and RESULTS are the
#     results of the stress tests
def get_updated_container_ids(old_containers, results, stress_type):
    if stress_type == 'ALL':
        return # Will Implement later
    elif stress_type == 'BINARY':
        # In this case, old_containers should be a tuple of dictionaries
        return get_updated_container_ids_binary(old_containers, results)
    return


# Old_containers MUST be a tuple of dictionaries (2)
def get_updated_container_ids_binary(old_containers, results):
    old_stress_dict1, old_stress_dict2 = old_containers
    results1, results2 = results

    # Check if iteration ends
    len1 = len(old_stress_dict1)
    len2 = len(old_stress_dict2)
    if (len1 == 1 and len2 == 0) or (len1 == 0 and len2 == 1):
        return None

    if compare_performance_binary(results1, results2): # Results indicate stress
        stress_dict1 = dict(old_stress_dict1.items()[len(old_stress_dict1)/2:])
        stress_dict2 = dict(old_stress_dict1.items()[:len(old_stress_dict1)/2])
    else:
        stress_dict1 = dict(old_stress_dict2.items()[len(old_stress_dict2)/2:])
        stress_dict2 = dict(old_stress_dict2.items()[:len(old_stress_dict2)/2])

    return stress_dict1,stress_dict2


# Returns true if the first set of results perform worse than the second
# Results1,2 must be a tuple (3)!
# This method should only be used for stress search type BINARY
# NOTE: Only considering the results from increment 50 for experimental purposes
def compare_performance_binary(results1, results2):
    results_cpu1, results_disk1, results_net1 = results1
    results_cpu2, results_disk2, results_net2 = results2
    results_list = [results_cpu1, results_disk1, results_net1, results_cpu2, results_disk2, results_net2]

    # avg_result defined this way to facilitate understanding (instead of just creating an arrays of 0's)
    avg_cpu1 = avg_cpu2 = avg_disk1 = avg_disk2 = avg_net1 = avg_net2 = 0
    avg_result = [avg_cpu1, avg_disk1, avg_net1, avg_cpu2, avg_disk2, avg_net2]

    # Shortened from having 6 separate for-loops
    index = 0
    for result_type in results_list:
        sum_50 = count_50 = baseline = 0
        for service, (container, (increment, delay)) in result_type:
            if increment == 0:
                baseline = delay
            else:
                sum_50 += baseline - delay
                count_50 += 1
        avg_result[index] = sum_50 / float(count_50)
        index += 1

    # Determining if results1 shows worse performance than results2
    degradation_points = 0
    # Comparing each category (CPU, DISK, NET) of result1 to result2
    index = 0
    while index < 3:
        if avg_result[index] > avg_result[3 + index]:
            degradation_points += 1
        index += 1

    return degradation_points >= 2


# Temporary main method to test get_container_ids function
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("public_vm_ips")
    parser.add_argument("--services_to_stress", help="List of services to stress on machines")
    parser.add_argument("--stress_all_services", action="store_true", help="Stress all services")
    parser.add_argument("--stress_search_type", help="Type of stress search")
    args = parser.parse_args()

    public_vm_ips = args.public_vm_ips.split(',')

    if (not args.services_to_stress and not args.stress_all_services):
        print 'Please specify the services to stress'
        exit()

    if args.stress_all_services:
        services = '*'
    else:
        services = args.services_to_stress.split(',')

    container_id_dict = get_container_ids(public_vm_ips, services, 'ALL')

    print 'All'

    for service, (vm_ip, container_id) in container_id_dict.iteritems():
        print '{}, ({},{})'.format(service, vm_ip, container_id)

    container_id_dict_tuple = get_container_ids(public_vm_ips, services, 'BINARY')

    container_id_dict,standby_dict = container_id_dict_tuple

    print 'First Half'

    for service, (vm_ip, container_id) in container_id_dict.iteritems():
        print '{}, ({},{})'.format(service, vm_ip, container_id)

    print 'Second Half'

    for service, (vm_ip, container_id) in standby_dict.iteritems():
        print '{}, ({},{})'.format(service, vm_ip, container_id)

    print 'Finished'
