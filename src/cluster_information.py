import remote_execution as remote_exec

'''
Queries information about the cluster.
Currently retrieves the information from quilt ps

CURRENT IMPL: Retrieve data from naive calls of quilt ps and docker ps
TODO: Retrieve the information from directly querying the Quilt key-value store

'''

### Pre-defined blacklist (Temporary)
quilt_blacklist = ['quilt/ovs', 'google/cadvisor:v0.24.1', 'quay.io/coreos/etcd:v3.0.2', 'mchang6137/quilt:latest']

# Find all the VMs in the current Quilt Cluster
# Returns a list of IP addresses
def get_actual_vms():
    return ['52.53.193.146']

# Find all the services in the current Quilt Cluster
# Returns a list of service names (strings)
def get_actual_services():
    return ['nginx:1.10']

# Given a machine type, identify the amount of resource on the machine
# Assumes that the entire cluster has the same machine type
# Return: Resource_type -> Maximum capacity
def get_instance_specs(machine_type, provider='aws-ec2'):
    resource_capacity = {}
    # TODO
    # 388 Mbps
    resource_capacity['NET'] = 388 * (10 ** 6)
    # 83.28 MB/s
    resource_capacity['DISK'] = 83.28 
    # 1
    resource_capacity['CPU-CORE'] = 1
    resource_capacity['CPU-QUOTA'] = 100
    resource_capacity['MEMORY'] = 8096
        
    return resource_capacity

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
            identifier_tuple = (vm_ip, container_id)
            if service_name not in service_to_deployment:
                service_to_deployment[service_name] = [identifier_tuple]
            else:
                service_to_deployment[service_name].append(identifier_tuple)
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
            if service in vm_to_service:
                vm_to_service[vm_ip].append(service)
            else:
                vm_to_service[vm_ip] = [service]
    return vm_to_service
