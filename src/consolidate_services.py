import csv

import argparse

from mr import MR
from instance_specs import *

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
    service_specs = {}

    for service in service_list:
        service_specs[service] = []
        for mr in mr_to_allocation:
            service_name = mr.service_name
            resource = mr.resource
            if service_name != service:
                continue
            service_specs[service].append(mr)

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

    if current_allocation[resource] + mr_requirement <= resource_capacity:
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
            if can_fit_machine(mr,
                               mr_allocation[mr],
                               machine_to_allocation[machine_index],
                               instance_dict) is False:
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

def first_fit_packer(mr_allocation, instance_type):
    instance_specs = get_instance_specs(instance_type)

    service_containers = {'haproxy:1.7': 3,
                          'elasticsearch:2.4': 1,
                          'kibana:4': 4,
                          'tsaianson/node-apt-app': 5,
                          'mysql:5.6.32': 1,
                          'hantaowang/logstash-postgres': 1}

    '''
    service_containers = {'haproxy:1.7': 1,
                          'quilt/mongo': 2,
                          'node-app:node-todo.git': 2
                          }
    '''

    service_to_mr = set_service_specs(service_containers, mr_allocation)

    machine_to_allocation = {}
    machine_to_allocation = initialize_capacity(machine_to_allocation, 0, instance_specs)

    machine_to_service = {}
    machine_to_service[0] = []

    number_machines = 1
    for service_name in service_containers:
        mr_list = service_to_mr[service_name]
        for container_number in range(service_containers[service_name]):
            fit_found,machine_index = update_if_possible(mr_list,
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

    print number_machines
    print machine_to_service

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resource_csv", help='resource configuration file')
    parser.add_argument("--instance_type", help='instance type')
    args = parser.parse_args()

    mr_allocation = parse_config_csv(args.resource_csv)
    first_fit_packer(mr_allocation, args.instance_type)

    
