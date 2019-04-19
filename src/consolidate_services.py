import csv
import argparse

from mr import MR
from instance_specs import *
from poll_cluster_state import *
from copy import deepcopy

import logging

# Bin pack resources
def parse_config_csv(resource_config_csv):
    mr_allocation = {}
    with open(resource_config_csv, 'rb') as resource_config:
        reader = csv.DictReader(resource_config)

        for row in reader:
            service_name = row['SERVICE']
            resource = row['RESOURCE']
            amount = float(row['AMOUNT'])
            amount_repr = row['REPR']

            # Convert REPR to RAW AMOUNT
            if amount_repr == 'RAW':
                mr = MR(service_name, resource, None)
                mr_allocation[mr] = amount

    return mr_allocation

# Needs to be run with the initial deployment that runs clampdown?
def combine_resources(mr_allocation, imr_list,
                      instance_type, resource_type='CPU-QUOTA'):
    vm_list = get_actual_vms()
    vm_to_service = get_vm_to_service(vm_list)
    imr_service_names = [imr.service_name for imr in imr_list]
    
    resource_capacity = get_instance_specs(instance_type)
    single_core_capacity = 100

    all_deploy_sets = []
    for vm in vm_to_service.keys():
        deploy_together = []
        resource_usage = 0
        
        # First determine if an IMR has been placed on the machine
        # Assume only one IMR per machine
        for service_name in vm_to_service[vm]:
            if service_name in imr_service_names:
                resource_usage += mr_allocation[MR(service_name, resource_type, None)]
                deploy_together.append(MR(service_name, resource_type, None))
                break

        # Next, look at the remianing services
        for service_name in vm_to_service[vm]:
            if service_name in imr_service_names:
                continue
            
            relevant_mr = MR(service_name, resource_type, None)
            if mr_allocation[relevant_mr] + resource_usage < single_core_capacity:
                resource_usage += mr_allocation[relevant_mr]
                deploy_together.append(MR(service_name, resource_type, None))

        all_deploy_sets.append(deploy_together)

        # Can't fill up remaining resources because it is no guarantee that other
        # instances will be able to sustain same resource growths.

    return all_deploy_sets

# Returns a list of MRs for each service
def set_service_specs(service_list, mr_to_allocation):
    #    resources = ('MEMORY', 'CPU-QUOTA', 'NET', 'DISK')
    service_specs = {}

    for service in service_list:
        tmp = []
        resources_seen = []
        for mr in mr_to_allocation:
            service_name = mr.service_name
            if service_name != service:
                continue
            tmp.append(mr)
            if mr.resource not in resources_seen:
                resources_seen.append(mr.resource)
                
        service_specs[service] = []
        for res in resources_seen:
            service_specs[service].append(filter(lambda x: x.resource == res, tmp)[0])

    return service_specs

def initialize_capacity(machine_to_allocation, machine_index, instance_specs):
    machine_to_allocation[machine_index] = {}

    machine_to_allocation[machine_index]['CPU-QUOTA'] = 0
    machine_to_allocation[machine_index]['CPU-CORE'] = 0
    machine_to_allocation[machine_index]['DISK'] = 0
    machine_to_allocation[machine_index]['NET'] = 0
    machine_to_allocation[machine_index]['MEMORY'] = 0

    return machine_to_allocation

# Tests is a specific MR can fit into a specific machine
def can_fit_machine(mr, mr_requirement, current_allocation, instance_dict):
    resource = mr.resource
    if resource == 'CPU-QUOTA':
        resource_capacity = instance_dict['CPU-CORE'] * 100
    else:
        resource_capacity = instance_dict[resource]

    if current_allocation[resource] + mr_requirement <= resource_capacity * 0.9:
        return True
    else:
        return False

# only call if can_fit_machine has already been called successfully
def update_consumption(mr, mr_requirement, machine_to_allocation, machine_index):
    resource = mr.resource
    machine_to_allocation[machine_index][resource] += mr_requirement
    return machine_to_allocation

# Update all the MRs in the mr_list
def update_if_possible(mr_list,
                       mr_allocation,
                       machine_to_allocation,
                       number_machines,
                       instance_dict):
    for machine_index in range(number_machines):
        fit_found = True
        for mr in mr_list:
            if not can_fit_machine(mr,
                                   mr_allocation[mr],
                                   machine_to_allocation[machine_index],
                                   instance_dict):
                fit_found = False
                break

        if fit_found:
            for mr in mr_list:
                update_consumption(mr,
                                   mr_allocation[mr],
                                   machine_to_allocation,
                                   machine_index)
            return True, machine_index

    return False, -1

# Place on a particular machine
def place_if_possible(mr_list,
                      mr_allocation,
                      machine_to_allocation,
                      machine_index,
                      instance_dict):


    assert machine_index in machine_to_allocation.keys()
    fit_found = True
    for mr in mr_list:
        if not can_fit_machine(mr,
                               mr_allocation[mr],
                               machine_to_allocation[machine_index],
                               instance_dict):
            fit_found = False
            break
    if fit_found:
        for mr in mr_list:
            update_consumption(mr,
                               mr_allocation[mr],
                               machine_to_allocation,
                               machine_index)
        return True
        
    return False

def roundup(x):
    return x if x % 100 == 0 else x + 100 - x % 100

# imr_list is an ordered list of IMRs, and the MIMR should be the first element
# round_up indicates that IMRs need to be rounded up
def ffd_pack(past_mr_allocation, instance_type, sort_by='CPU-QUOTA', imr_list=[],
             deploy_together=[], round_up=False):
    mr_allocation = deepcopy(past_mr_allocation)
    
    if round_up is True:
        for imr in imr_list:
            assert imr in mr_allocation
            mr_allocation[imr] = roundup(mr_allocation[imr])

    # Use the below if you have already deployed the containers on quilt
    # Otherwise, define it manually.
    vm_list = get_actual_vms()
    service_placements = get_service_placements(vm_list)

    service_configurations = [mr.to_string().split(',')[0] for mr in mr_allocation.keys()]
    service_containers = []
    for service_name in service_placements:
        if service_name in service_configurations:
            service_containers += [service_name for x in range(len(service_placements[service_name]))]

    for affinity in deploy_together:
        for mr in affinity:
            service_containers.remove(mr.service_name)

    # Create a fake MR with the combination of MRs
    for affinity in deploy_together:
        affinity_services = ''
        total_resources = 0
        for mr in affinity:
            affinity_services += '&' + mr.service_name
            total_resources += mr_allocation[mr]
        mr_allocation[MR(affinity_services, 'CPU-QUOTA', None)] = roundup(total_resources)
        service_containers.append(affinity_services)

    service_to_mr = set_service_specs(service_containers, mr_allocation) # Amend to include affinities

    # IMR Aware Scheduling
    def imr_aware(sc, num_machines):
        sc_copy = deepcopy(sc)
        if num_machines == 1:
            return None
        
        instance_specs = get_instance_specs(instance_type)

        machine_to_allocation = {}
        for x in range(num_machines):
            machine_to_allocation = initialize_capacity(machine_to_allocation, x, instance_specs)
        
        machine_to_service = {}
        for x in range(num_machines):
            machine_to_service[x] = []

        resource_to_impacted_service = {}
        service_encountered = []
        # Find the IMRs and place them
        for mr in imr_list:
            if mr.service_name in service_encountered:
                continue
            else:
                service_encountered.append(mr.service_name)
                    
            if mr.resource not in resource_to_impacted_service:
                resource_to_impacted_service[mr.resource] = []
            resource_to_impacted_service[mr.resource].append(mr.service_name)

        # First start by round robin the MIMR and other MRs that are of the same resource
        mimr_resource = imr_list[0].resource
        service_list = resource_to_impacted_service[mimr_resource]
        containers_seen = 0
        for service_name in service_list:
            num_service_containers = sc_copy.count(service_name)
            mr_list = service_to_mr[service_name]

            # Round robin the placements
            for container_index in range(num_service_containers):
                machine_index = (containers_seen + container_index) % num_machines
                fit_found = place_if_possible(mr_list,
                                              mr_allocation,
                                              machine_to_allocation,
                                              machine_index,
                                              instance_specs)
                if fit_found:
                    machine_to_service[machine_index].append(service_name)
                    containers_seen += 1
                else:
                    logging.error('You have selected too many IMRs for consideration!')
                    return {}

        # Don't double count the services
        for service_name in service_list:
            sc_copy = filter(lambda a: a != service_name, sc_copy)
            
        # Reverse the order of the services packed into the machine
        new_machine_to_allocation = {}
        new_machine_to_service = {}
        for machine_index in machine_to_allocation:
            new_machine_to_allocation[num_machines - machine_index - 1] = machine_to_allocation[machine_index]
            new_machine_to_service[num_machines - machine_index - 1] = machine_to_service[machine_index]
        machine_to_allocation = new_machine_to_allocation
        machine_to_service = new_machine_to_service

        

        # Then do a first fit with any remaining MR.
        for service_name in sc_copy:
            mr_list = service_to_mr[service_name]
            fit_found, machine_index = update_if_possible(mr_list,
                                                          mr_allocation,
                                                          machine_to_allocation,
                                                          num_machines,
                                                          instance_specs)

            if fit_found:
                machine_to_service[machine_index].append(service_name)
            else:
                logging.error('No valid placement found. Returning')
                return {}

        return machine_to_service

    def ff(sc):
        instance_specs = get_instance_specs(instance_type)

        machine_to_allocation = {}
        machine_to_allocation = initialize_capacity(machine_to_allocation, 0, instance_specs)

        machine_to_service = {}
        machine_to_service[0] = []

        number_machines = 1
        for service_name in sc:
            mr_list = service_to_mr[service_name]
            fit_found, machine_index = update_if_possible(mr_list,
                                                          mr_allocation,
                                                          machine_to_allocation,
                                                          number_machines,
                                                          instance_specs)

            if fit_found:
                machine_to_service[machine_index].append(service_name)

            if fit_found is False:
                number_machines += 1
                machine_to_allocation[number_machines - 1] = {}
                machine_to_service[number_machines - 1] = []
                initialize_capacity(machine_to_allocation, number_machines - 1, instance_specs)
                fit_found, machine_index = update_if_possible(mr_list,
                                                              mr_allocation,
                                                              machine_to_allocation,
                                                              number_machines,
                                                              instance_specs)
                machine_to_service[machine_index].append(service_name)

                if fit_found is False:
                    logging.error('Fit not found. You have a bug. Exiting..')
                    exit()

        return machine_to_service

    resource_index = {}
    for service in service_to_mr:
        for x in range(len(service_to_mr[service])):
            resource_index[service_to_mr[service][x].resource] = x

    # First find the number of machines from first fit
    imr_resource = imr_list[0].resource
    service_containers = sorted(service_containers,
                                key=lambda x: mr_allocation[service_to_mr[x][resource_index[imr_resource]]])

    print service_containers
    first_fit_placements = ff(service_containers)
    print first_fit_placements
    logging.info('First fit service placement is {}'.format(first_fit_placements))

    # First place the services that show up as MIMRs
    optimal_num_machines = len(first_fit_placements.keys())
    imr_aware_service_placement = {}
    imr_aware_service_placement = imr_aware(service_containers, optimal_num_machines)
    if imr_aware_service_placement is None:
        imr_aware_service_placement = first_fit_placements
    while len(imr_aware_service_placement.keys()) == 0:
        optimal_num_machines += 1
        imr_aware_service_placement = imr_aware(service_containers, optimal_num_machines)
        if len(imr_aware_service_placement.keys()) != 0:
            break

    logging.info('IMR Aware Service Placement is {}'.format(imr_aware_service_placement))
    return first_fit_placements, imr_aware_service_placement

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resource_csv", help='resource configuration file')
    parser.add_argument("--instance_type", help='instance type')
    args = parser.parse_args()

    allocations = parse_config_csv(args.resource_csv)
    
    # Must re-select this
    imr_list = [MR('node-app:node-todo.git', 'CPU-QUOTA', None)]
    ffp, iap = ffd_pack(allocations, args.instance_type, imr_list[0].resource, imr_list)
    print ffp
    print iap
