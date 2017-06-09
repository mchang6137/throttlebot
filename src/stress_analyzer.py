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
            if (services == '*' or (container_commands[i] in services))
                container_id_dict[container_commands[i]] = (vm_ip, container_ids[i])

    return container_id_dict

# Returns a tuple of dictionaries of the services and respective container_ids
# The first dictionary holds the containers to be Stressed
def get_container_ids_binary(vm_ips, services):
    container_id_dict = get_container_ids_all(vm_ips, services)
    stress_dict = dict(container_id_dict.items()[len(container_id_dict)/2:])
    standby_dict = dict(container_id_dict.items()[:len(container_id_dict)/2])
    
    return stress_dict,standby_dict


### Functions below are for updating container dictionaries

# Returns an updated dictionary of the containers to stress based on type
# OLD_CONTAINERS is the previous dictionary of containers, and RESULTS are the
#     results of the stress tests
def get_updated_container_ids(old_containers, results, stress_type):
    if stress_type == 'ALL':
        return # Will Implement later
    elif stress_type == 'BINARY':
        # In this case, old_containers should be a tuple
        return get_updated_container_ids_binary(old_containers, results)
    return


# Old_containers MUST be a tuple of dictionaries (2)
def get_updated_container_ids_binary(old_containers, results):
    old_stress_dict, old_standby_dict = old_containers
    if (True): # Results indicate stress
        stress_dict = dict(old_stress_dict.items()[len(old_stress_dict)/2:])
        standby_dict = dict(old_stress_dict.items()[:len(old_stress_dict)/2])
    else:
        stress_dict = dict(old_standby_dict.items()[len(old_standby_dict)/2:])
        standby_dict = dict(old_standby_dict.items()[:len(old_standby_dict)/2])

    return stress_dict,standby_dict

# Temporary main method to test get_container_ids function (NOT UPDATED)
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("public_vm_ips")
    parser.add_argument("--services_to_stress", help="List of services to stress on machines")
    parser.add_argument("--stress_all_services", action="store_true", help="Stress all services")
    args = parser.parse_args()

    public_vm_ips = args.public_vm_ips.split(',')

    if (not args.services_to_stress and not args.stress_all_services):
        print 'Please specify the services to stress'
        exit()

    if args.stress_all_services:
        services = '*'
    else:
        services = args.services_to_stress.split(',')

    container_id_dict = get_container_ids(public_vm_ips, services)

    for service, (vm_ip, container_id) in container_id_dict.iteritems():
        print '{}, ({},{})'.format(service, vm_ip, container_id)

    print 'Finished'
