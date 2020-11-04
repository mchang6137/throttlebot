import argparse
import numpy as np
import csv
import os
import ConfigParser

from modify_resources import *
from remote_execution import *
from poll_cluster_state import *
from instance_specs import *
from stress_analyzer import *

def reset_all_resources():
    vm_list = get_actual_vms()
    service_placements = get_service_placements(vm_list)
    all_services = get_actual_services()
    all_resources = get_stressable_resources()

    vm_to_service = get_vm_to_service(vm_list)
    mr_list = get_all_mrs_cluster(vm_list, all_services, all_resources)

    for mr in mr_list:
        reset_mr_provision(mr, None)

    print 'Reset all mr in mr_list'

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--last_completed_iter", type=int, default=0, help="Last iteration completed")
    args = parser.parse_args()

    reset_all_resources()
