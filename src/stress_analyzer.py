import argparse
import numpy as np
import remote_execution as remote_exec

from cluster_information import *
from random import shuffle

### Pre-defined blacklist (Temporary)
blacklist = ['quilt/ovs', 'google/cadvisor:v0.24.1', 'quay.io/coreos/etcd:v3.0.2', 'mchang6137/quilt:latest']

class MR:
    def __init__(self, service_name, resource, instances):
        self.service_name = service
        self.resource = resource
        self.instances = instances

# Opening function to generate any kind of function
def generate_mr_from_policy(vm_ips, services, resources, stress_policy):
    if stress_policy == 'ALL':
        return get_all_mrs(vm_ips, services, resources):
    else:
        print 'This stress policy does not exist; defaulting to ALL stress'
        return get_container_ids_all(vm_ips, services)
    
# Policy that returns all MRs subject to restrictions on
# VMs, service names, and resources
def get_all_mrs(vm_list, services, resources):
    mr_schedule = [] 
    service_to_deployment = get_service_placements(vm_list)
    
    for service in service_to_deployment:
        if service in services:
            continue
        deployments = service_to_deployment[service]
        for resource in resources:
            mr_schedule.add(MR(service, resource, deployments))
            
    return mr_schedule

# Returns a dictionary of the services and their respective container_ids
# VM_IPS is a list of ip addresses, and SERVICES is a list of services
# Note: Services are the container image names (Temporary)
def get_container_ids_all(vm_ips, services):
    container_id_dict = {}
    for vm_ip in vm_ips:
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
