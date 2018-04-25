import csv
import argparse

from mr import MR
from instance_specs import *
from poll_cluster_state import *

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

# imr_list is an ordered list of IMRs, and the MIMR should be the first element
def ffd_pack(mr_allocation, instance_type, sort_by='CPU-QUOTA', imr_list=[]):
    """
    FFD based on each resource type

    Should get near optimal packing efficiency,
    in single dimensional case, efficiency is
    11/9 OPT. Multidimensional is probably much
    worse.
    """

    # At present, I have no way to infer this, so it will have to be changed
    # for each project manually
    '''
    service_containers = [
        'haproxy:1.7',
        'elasticsearch:2.4',
        'kibana:4',
        'kibana:4',
        'kibana:4',
        'kibana:4',
        'tsaianson/node-apt-app',
        'tsaianson/node-apt-app',
        'tsaianson/node-apt-app',
        'mysql:5.6.32',
        'hantaowang/logstash-postgres',
        'library/postgres:9.4',
    ]
    '''

    # Use the below if you have already deployed the containers on quilt
    # Otherwise, define it manually.
    vm_list = get_actual_vms()
    service_placements = get_service_placements(vm_list)

    service_configurations = [mr.to_string().split(',')[0] for mr in mr_allocation.keys()]
    service_containers = []
    for service_name in service_placements:
        if service_name in service_configurations:
            service_containers += [service_name for x in range(len(service_placements[service_name]))]

    service_to_mr = set_service_specs(service_containers, mr_allocation)

    # IMR Aware Scheduling
    def imr_aware(sc, num_machines):
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
        for service_name in service_list:
            num_service_containers = sc.count(service_name)
            mr_list = service_to_mr[service_name]

            # Round robin the placements
            for container_index in range(num_service_containers):
                machine_index = container_index % num_machines
                fit_found = place_if_possible(mr_list,
                                              mr_allocation,
                                              machine_to_allocation,
                                              machine_index,
                                              instance_specs)
                if fit_found:
                    machine_to_service[machine_index].append(service_name)
                else:
                    print 'something is wrong in the round robin placements'
                    exit()

        # Don't double count the services
        for service_name in service_list:
            sc.remove(service_name)
            
        # Reverse the order of the services packed into the machine
        new_machine_to_allocation = {}
        new_machine_to_service = {}
        for machine_index in machine_to_allocation:
            new_machine_to_allocation[num_machines - machine_index - 1] = machine_to_allocation[machine_index]
            new_machine_to_service[num_machines - machine_index - 1] = machine_to_service[machine_index]
        machine_to_allocation = new_machine_to_allocation
        machine_to_service = new_machine_to_service
        
        # Then do a first fit with any remaining MR.
        for service_name in sc:
            mr_list = service_to_mr[service_name]
            fit_found, machine_index = update_if_possible(mr_list,
                                                          mr_allocation,
                                                          machine_to_allocation,
                                                          num_machines,
                                                          instance_specs)

            if fit_found:
                machine_to_service[machine_index].append(service_name)
            else:
                print 'No valid placement found. Returning'
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
                    print 'Fit not found. You have a bug. Exiting..'
                    exit()

        return machine_to_service

    resource_index = {'MEMORY': 0,
                      'CPU-QUOTA': 1,
                      'NET': 2,
                      'DISK': 3}

    # First find the number of machines from first fit
    imr_resource = imr_list[0].resource
    service_containers = sorted(service_containers,
                                key=lambda x: mr_allocation[service_to_mr[x][resource_index[imr_resource]]])
    service_containers.reverse()
    service_placements = ff(service_containers)
    print service_placements

    # First place the services that show up as MIMRs
    optimal_num_machines = len(service_placements.keys())
    imr_aware_service_placement = imr_aware(service_containers, optimal_num_machines)
    if len(imr_aware_service_placement.keys()) == 0:
        return service_placements, False
    else:
        return imr_aware_service_placement, True

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resource_csv", help='resource configuration file')
    parser.add_argument("--instance_type", help='instance type')
    args = parser.parse_args()

    allocations = parse_config_csv(args.resource_csv)
    imr_list = [MR('haproxy:1.7', 'CPU-QUOTA', None)]
    ffd_pack(allocations, args.instance_type, imr_list[0].resource, imr_list)
