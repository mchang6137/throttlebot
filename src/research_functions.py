'''
Research functions solely for the purpose of experimentation and getting results for Eurosys
'''
import argparse

import modify_resources as resource_modifier
from instance_specs import *
from poll_cluster_state import *
from stress_analyzer import *

def reset_resources():
    vm_list = get_actual_vms()
    all_services = get_actual_services()
    all_resources = get_stressable_resources()

    mr_list = get_all_mrs_cluster(vm_list, all_services, all_resources)
    print 'Resetting provisions for {}'.format([mr.to_string() for mr in mr_list])

    for mr in mr_list:
        resource_modifier.reset_mr_provision(mr)

    print 'All MRs reset'

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset_resources", action="store_true", help="Reset all resource allocation")
    args = parser.parse_args()

    if args.reset_resources:
        reset_resources()
        
