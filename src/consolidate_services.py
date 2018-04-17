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
    resources = ('MEMORY', 'CPU-QUOTA', 'NET', 'DISK')
    service_specs = {}

    for service in service_list:
        tmp = []
        for mr in mr_to_allocation:
            service_name = mr.service_name
            if service_name != service:
                continue
            tmp.append(mr)
        service_specs[service] = []
        for res in resources:
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


def ffd_pack(mr_allocation, instance_type):
    """
    FFD based on each resource type

    Should get near optimal packing efficiency,
    in single dimensional case, efficiency is
    11/9 OPT. Multidimensional is probably much
    worse.
    """

    # At present, I have no way to infer this, so it will have to be changed
    # for each project manually
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

    service_to_mr = set_service_specs(service_containers, mr_allocation)

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

        print number_machines
        print machine_to_service

    service_containers = sorted(service_containers, key=lambda x: mr_allocation[service_to_mr[x][0]])
    service_containers.reverse()
    print "MEMORY"
    ff(service_containers)

    service_containers = sorted(service_containers, key=lambda x: mr_allocation[service_to_mr[x][1]])
    service_containers.reverse()
    print 'CPU-QUOTA'
    ff(service_containers)

    service_containers = sorted(service_containers, key=lambda x: mr_allocation[service_to_mr[x][2]])
    service_containers.reverse()
    print 'NET'
    ff(service_containers)

    service_containers = sorted(service_containers, key=lambda x: mr_allocation[service_to_mr[x][3]])
    service_containers.reverse()
    print 'DISK'
    ff(service_containers)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resource_csv", help='resource configuration file')
    parser.add_argument("--instance_type", help='instance type')
    args = parser.parse_args()

    allocations = parse_config_csv(args.resource_csv)
    ffd_pack(allocations, args.instance_type)
