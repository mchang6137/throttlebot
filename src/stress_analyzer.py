import argparse
import numpy as np
import remote_execution as remote_exec
from random import shuffle

### Pre-defined blacklist (Temporary)
blacklist = ['quilt/ovs', 'google/cadvisor:v0.24.1', 'quay.io/coreos/etcd:v3.0.2', 'mchang6137/quilt:latest',
             'tsaianson/netflushclient']

### Functions below are for getting initial container dictionaries

# Function that calls on the correct get_container function based on POLICY
def get_container_ids(vm_ips, services, resources, stress_policy):
    if stress_policy == 'ALL':
        return get_container_ids_all(vm_ips, services)
    elif stress_policy == 'BINARY': # Shevled for later
        return get_container_ids_binary(vm_ips, services)
    elif stress_policy == 'HALVING':
        return get_container_ids_halving(vm_ips, services, resources)


# Returns a dictionary of the services and their respective container_ids
# VM_IPS is a list of ip addresses, and SERVICES is a list of services
# Note: Services are the container image names (Temporary)
# Only function that currently supports multi-container stressing
def get_container_ids_all(vm_ips, services):
    container_id_dict = {}
    for vm_ip in vm_ips:
        # MULTI-SERVICE is not updated
        if isinstance(vm_ip, list):
            sub_container_dict = {}
            for i in range(len(vm_ip)):
                vm_ip_current = vm_ip[i]
                ssh_client = remote_exec.get_client(vm_ip_current)
                docker_container_id = 'docker ps | tr -s \' \' | cut -d \' \' -f1 | tail -n +2'
                # docker_container_cmd = 'docker ps --no-trunc | grep -oP \'\"\K[^\"]+(?=[\"])\''
                docker_container_image = 'docker ps | tr -s \' \' | cut -d \' \' -f2 | tail -n +2'
                _, stdout1, _ = ssh_client.exec_command(docker_container_id)
                container_ids = stdout1.read().splitlines()
                _, stdout2, _ = ssh_client.exec_command(docker_container_image)
                container_images = stdout2.read().splitlines()
                for j in range(len(container_ids)):
                    if container_images[j] not in blacklist and (services == '*' or (container_images[j] in services)):
                        if container_images[j] in sub_container_dict:
                            sub_container_dict[container_images[j]].append((vm_ip_current, container_ids[j]))
                        else:
                            sub_container_dict[container_images[j]] = [(vm_ip_current, container_ids[j])]
            service_list = []
            vm_list = []
            container_list = []
            for service, ip_cont_tuple_list in sub_container_dict.iteritems():
                for ip_cont_tuple in ip_cont_tuple_list:
                    ip_address, container_id = ip_cont_tuple
                    if service not in service_list:
                        service_list.append(service)
                        vm_list.append([])
                        container_list.append([])
                    service_index = service_list.index(service)
                    vm_list[service_index].append(ip_address)
                    container_list[service_index].append(container_id)
            for i in range(len(service_list)):
                if service_list[i] in container_id_dict:
                    container_id_dict[service_list[i]].append((vm_list[i], container_list[i]))
                else:
                    container_id_dict[service_list[i]] = [(vm_list[i], container_list[i])]
        else:
            ssh_client = remote_exec.get_client(vm_ip)
            docker_container_id = 'docker ps | tr -s \' \' | cut -d \' \' -f1 | tail -n +2'
            # docker_container_cmd = 'docker ps --no-trunc | grep -oP \'\"\K[^\"]+(?=[\"])\''
            docker_container_image = 'docker ps | tr -s \' \' | cut -d \' \' -f2 | tail -n +2'
            _, stdout1, _ = ssh_client.exec_command(docker_container_id)
            container_ids = stdout1.read().splitlines()
            _, stdout2, _ = ssh_client.exec_command(docker_container_image)
            container_images = stdout2.read().splitlines()
            for i in range(len(container_ids)):
                if container_images[i] not in blacklist and (services == '*' or (container_images[i] in services)):
                    if container_images[i] in container_id_dict:
                        container_id_dict[container_images[i]].append((vm_ip, container_ids[i]))
                    else:
                        container_id_dict[container_images[i]] = [(vm_ip, container_ids[i])]

    return container_id_dict

# Shelved for later. Need to fix for dict/list update
# Returns a tuple of dictionaries of the services and respective container_ids
# The first dictionary holds the containers to be Stressed
def get_container_ids_binary(vm_ips, services):
    container_id_dict = get_container_ids_all(vm_ips, services)
    if container_id_dict is None:
        return None
    container_id_list = container_id_dict.items()
    shuffle(container_id_list)
    stress_dict1 = dict(container_id_list[len(container_id_list)/2:])
    stress_dict2 = dict(container_id_list[:len(container_id_list)/2])

    return stress_dict1,stress_dict2


def get_container_ids_halving(vm_ips, services, resources):
    container_id_dict = get_container_ids_all(vm_ips, services)
    container_id_list = []
    for service, tuplelist in container_id_dict.iteritems():
        for vm_ip, container_id in tuplelist:
            for resource in resources:
                container_id_list.append((service, (vm_ip, (container_id, resource))))

    shuffle(container_id_list)
    # Converting list of tuples back into dictionaries
    stress_list1 = container_id_list[len(container_id_list)/2:]
    stress_list2 = container_id_list[:len(container_id_list)/2]

    stress_dict1 = {}
    for (service, (vm_ip, (container_id, resource))) in stress_list1:
        if service in stress_dict1:
            stress_dict1[service].append((vm_ip, (container_id, resource)))
        else:
            stress_dict1[service] = [(vm_ip, (container_id, resource))]

    stress_dict2 = {}
    for (service, (vm_ip, (container_id, resource))) in stress_list2:
        if service in stress_dict2:
            stress_dict2[service].append((vm_ip, (container_id, resource)))
        else:
            stress_dict2[service] = [(vm_ip, (container_id, resource))]

    return stress_dict1,stress_dict2


### Functions below are for updating container dictionaries

# Returns an updated dictionary of the containers to stress based on type
# OLD_CONTAINERS is the previous dictionary of containers, and RESULTS are the
#     results of the stress tests
def get_updated_container_ids(old_containers, results, stress_policy):
    if stress_policy == 'ALL':
        return None
    elif stress_policy == 'BINARY' or stress_policy == 'HALVING':
        # In this case, old_containers should be a tuple of dictionaries
        return get_updated_container_ids_binary_halving(old_containers, results)
    return

# Old_containers MUST be a tuple of dictionaries (2)
def get_updated_container_ids_binary_halving(old_containers, results):
    old_stress_dict1, old_stress_dict2 = old_containers
    results1, results2 = results

    # Check if iteration ends
    len1 = len(old_stress_dict1)
    len2 = len(old_stress_dict2)
    if (len1 == 1 and len2 == 0) or (len1 == 0 and len2 == 1):
        return None

    if compare_performance_binary_halving(results1, results2):
        new_stress_list = []
        for service, tuplelist in old_stress_dict1.iteritems():
            for vm_ip, (container_id, resource) in tuplelist:
                new_stress_list.append((service, (vm_ip, (container_id, resource))))
    else:
        new_stress_list = []
        for service, tuplelist in old_stress_dict2.iteritems():
            for vm_ip, (container_id, resource) in tuplelist:
                new_stress_list.append((service, (vm_ip, (container_id, resource))))

    shuffle(new_stress_list)
    stress_list1 = new_stress_list[len(new_stress_list)/2:]
    stress_list2 = new_stress_list[:len(new_stress_list)/2]

    stress_dict1 = {}
    for (service, (vm_ip, (container_id, resource))) in stress_list1:
        if service in stress_dict1:
            stress_dict1[service].append((vm_ip, (container_id, resource)))
        else:
            stress_dict1[service] = [(vm_ip, (container_id, resource))]

    stress_dict2 = {}
    for (service, (vm_ip, (container_id, resource))) in stress_list2:
        if service in stress_dict2:
            stress_dict2[service].append((vm_ip, (container_id, resource)))
        else:
            stress_dict2[service] = [(vm_ip, (container_id, resource))]

    return stress_dict1,stress_dict2


# Returns true if the first set of results perform worse than the second
# Results1,2 must be a tuple (3)!
# This method should only be used for stress search type BINARY or HALVING
# NOTE: Only considering the results from increment 50 for experimental purposes
def compare_performance_binary_halving(results1, results2):
    results_cpu1, results_disk1, results_net1 = results1
    results_cpu2, results_disk2, results_net2 = results2
    results_list = [results_cpu1, results_disk1, results_net1, results_cpu2, results_disk2, results_net2]

    # avg_result defined this way to facilitate understanding (instead of just creating an arrays of 0's)
    avg_cpu1 = avg_cpu2 = avg_disk1 = avg_disk2 = avg_net1 = avg_net2 = 0
    avg_result = [avg_cpu1, avg_disk1, avg_net1, avg_cpu2, avg_disk2, avg_net2]

    # Shortened from having 6 separate for-loops
    index = 0
    for result_type in results_list:
        sum_50 = count_50 = 0

        for service, containerd in result_type.iteritems():
            for container, incrementd in containerd.iteritems():
                baseline_dict = {} # Each metric will have a different baseline
                # Calculating baseline first
                for increment, metricd in incrementd.iteritems():
                    if increment == 0:
                        for metric, delays  in metricd.iteritems():
                            baseline_dict[metric] = np.mean(delays)
                for increment, metricd in incrementd.iteritems():
                    if increment != 0:
                        for metric, delays in metricd.iteritems():
                            sum_50 += np.mean(delays) - baseline_dict[metric]
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
    parser.add_argument("--resources_to_stress", help="List of resources to stress on machines")
    parser.add_argument("--stress_all_resources", action="store_true", help="Stress all resources")
    parser.add_argument("--stress_search_policy", help="Type of stress policy")
    args = parser.parse_args()

    public_vm_ips = args.public_vm_ips.split(',')

    if (not args.services_to_stress and not args.stress_all_services):
        print 'Please specify the services to stress'
        exit()

    if (not args.resources_to_stress and not args.stress_all_resources):
        print 'Please specify the resources to stress'
        exit()

    if args.stress_all_services:
        services = '*'
    else:
        services = args.services_to_stress.split(',')

    if args.stress_all_resources:
        resources = ['CPU','DISK','NET']
    else:
        resources = args.resources_to_stress.split(',')

    container_id_dict = get_container_ids(public_vm_ips, services, resources, 'ALL')

    print 'All'

    for service, tuplelist in container_id_dict.iteritems():
        for vm_ip, container_id in tuplelist:
            print '{}, ({},{})'.format(service, vm_ip, container_id)

    container_id_dict1, container_id_dict2 = get_container_ids(public_vm_ips, services, resources, 'HALVING')

    print 'First Half'

    for service, tuplelist in container_id_dict1.iteritems():
        for (vm_ip, (container_id, resource)) in tuplelist:
            print '{}, ({}, ({}, {}))'.format(service, vm_ip, container_id, resource)

    print 'Second Half'

    for service, tuplelist in container_id_dict2.iteritems():
        for (vm_ip, (container_id, resource)) in tuplelist:
            print '{}, ({}, ({}, {}))'.format(service, vm_ip, container_id, resource)

    print 'Entering loop'

    newtup = (container_id_dict1, container_id_dict2)
    # Testing if the splitting works (Must override condition in function)
    while True:

        print 'Splitting First Half'

        newtup = get_updated_container_ids_binary_halving(newtup, ('hi','hi'))
        if newtup is None:
            break
        new1,new2 = newtup

        print 'New First Half'

        for service, tuplelist in new1.iteritems():
            for (vm_ip, (container_id, resource)) in tuplelist:
                print '{}, ({}, ({}, {}))'.format(service, vm_ip, container_id, resource)

        print 'New Second Half'

        for service, tuplelist in new2.iteritems():
            for (vm_ip, (container_id, resource)) in tuplelist:
                print '{}, ({}, ({}, {}))'.format(service, vm_ip, container_id, resource)

    print 'Finished'
