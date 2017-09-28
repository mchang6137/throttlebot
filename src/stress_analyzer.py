import argparse
import numpy as np
import remote_execution as remote_exec

from cluster_information import *
from random import shuffle
import redis_resource as resource_datastore

from mr import MR

### Pre-defined blacklist (Temporary)
blacklist = ['quilt/ovs', 'google/cadvisor:v0.24.1', 'quay.io/coreos/etcd:v3.0.2', 'mchang6137/quilt:latest']

# Returns a list of MRs to stress in following iterations
def generate_mr_from_policy(redis_db, stress_policy):
    # Retrieves all MRs directly from Cluster information
    if stress_policy == 'ALL':
        return resource_datastore.get_all_mrs(redis_db)
    else:
        print 'This stress policy does not exist; defaulting to ALL stress'
        return resource_datastore.get_all_mrs(redis_db)

# Policy that returns all MRs subject to restrictions on
# VMs, service names, and resources
def get_all_mrs_cluster(vm_list, services, resources):
    mr_schedule = []
    service_to_deployment = get_service_placements(vm_list)
    
    for service in service_to_deployment:
        if service not in services:
            continue
        deployments = service_to_deployment[service]
        for resource in resources:
            mr_schedule.append(MR(service, resource, deployments))
            
    return mr_schedule

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


