import subprocess
import remote_execution as remote_exec

'''
Queries information about the cluster directly from the true state
Currently retrieves the information from quilt ps

CURRENT IMPL: Retrieve data from naive calls of quilt ps and docker ps
TODO: Retrieve the information from directly querying the Quilt key-value store

'''

### Pre-defined blacklist (Temporary)
quilt_blacklist = ['quilt/ovs', 'google/cadvisor:v0.24.1', 'quay.io/coreos/etcd:v3.0.2', 'mchang6137/quilt:latest',
                   'throttlebot/quilt:latest']

# Find all the VMs in the current Quilt Cluster
# Returns a list of IP addresses
def get_actual_vms():
    ps_args = ['quilt', 'ps']
    awk_args = ["awk", r'{print $6}']

    # Identify the machine index of the master node
    machine_roles = parse_quilt_ps_col(2, machine_level=True)

    # Get the IP addresses of all the machines
    machine_ips = parse_quilt_ps_col(6, machine_level=True)

    combined_machine_info = zip(machine_roles, machine_ips)
    ips = []
    for info in combined_machine_info:
        role,ip = info
        if role == 'Master':
            continue
        ips.append(ip)
    return ips

# Gets all the services in the Quilt cluster
# Identifies the services based on the COMMAND
def get_actual_services():
    services = parse_quilt_ps_col(3, machine_level=False)
    return services

def parse_quilt_ps_col(column, machine_level=True):
    ps_args = ['quilt', 'ps']
    awk_args = ["awk", r'{{print ${}}}'.format(column)]

    ps = subprocess.Popen(ps_args, stdout=subprocess.PIPE)
    col_results = subprocess.check_output(awk_args, stdin=ps.stdout)
    result_list = []
    if machine_level:
        for result in col_results.splitlines():
            if result == '':
                break
            result_list.append(result)
        return result_list[1:]
    else:
        below_line = False
        for result in col_results.splitlines():
            if result == '':
                below_line = True
                continue
            if below_line:
                result_list.append(result)
        return result_list[1:]

def get_quilt_services():
    return quilt_blacklist

# Returns all stressable resources available for this
def get_stressable_resources(cloud_provider='aws-ec2'):
    all_resources = ['CPU-CORE', 'CPU-QUOTA', 'NET', 'DISK', 'MEMORY']
    return all_resources

# Identify the container id and VM where a service might be residing
# Return service_name -> (vm_ip, container_id)
def get_service_placements(vm_ips):
    service_to_deployment = {}
    for vm_ip in vm_ips:
        ssh_client = remote_exec.get_client(vm_ip)
        docker_container_id_cmd = 'docker ps | tr -s \' \' | cut -d \' \' -f1 | tail -n +2'
        docker_container_image_cmd = 'docker ps | tr -s \' \' | cut -d \' \' -f2 | tail -n +2'
        _, stdout1, _ = ssh_client.exec_command(docker_container_id_cmd)
        container_ids = stdout1.read().splitlines()
        _, stdout2, _ = ssh_client.exec_command(docker_container_image_cmd)
        service_names = stdout2.read().splitlines()

        zipped_name_id = zip(service_names, container_ids)

        #Assume that the container ids and the service names are ordered in the same way
        for service_name, container_id in zipped_name_id:
            if service_name[-4:] == '.git':
                service_name = service_name[service_name.index('/')+1:]
            identifier_tuple = (vm_ip, container_id)
            if service_name not in service_to_deployment:
                service_to_deployment[service_name] = [identifier_tuple]
            else:
                service_to_deployment[service_name].append(identifier_tuple)
        remote_exec.close_client(ssh_client)
    return service_to_deployment

# Identify the services residing on each VM
def get_vm_to_service(vm_ips):
    vm_to_service = {}
    for vm_ip in vm_ips:
        ssh_client = remote_exec.get_client(vm_ip)
        docker_container_id_cmd = 'docker ps | tr -s \' \' | cut -d \' \' -f1 | tail -n +2'
        docker_container_image_cmd = 'docker ps | tr -s \' \' | cut -d \' \' -f2 | tail -n +2'
        _, stdout1, _ = ssh_client.exec_command(docker_container_image_cmd)
        service_names = stdout1.read().splitlines()

        #Assume that the container ids and the service names are ordered in the same way
        for service in service_names:
            if service in quilt_blacklist:
                continue
            if vm_ip in vm_to_service:
                vm_to_service[vm_ip].append(service)
            else:
                vm_to_service[vm_ip] = [service]
        remote_exec.close_client(ssh_client)
    return vm_to_service
