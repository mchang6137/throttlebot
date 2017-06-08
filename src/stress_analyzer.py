import argparse
from remote_execution import *


# Returns a dictionary of the services and their respective container_ids
# VM_IPS is a list of ip addresses, and SERVICES is a list of services
def get_container_ids(vm_ips, services):
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


# Returns an updated dictionary of the containers to stress
# OLD_CONTAINERS is the previous dictionary of containers, and RESULTS are the
#     results of the stress tests
def get_updated_container_ids(old_containers, results):
    # Will implement later
    return


# Temporary main method to test get_container_ids function
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
