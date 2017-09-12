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
    return ['54.183.176.238']

# Find all the services in the current Quilt Cluster
# Returns a list of service names (strings)
def get_actual_services():
    return ['tsaianson/disknetflush']

# Given a machine type, identify the amount of resource on the machine
# Assumes that the entire cluster has the same machine type
# Return: Resource_type -> Maximum capacity {CPU: # of cores, DISK: I/O time in MBps, NET: bandwidth in Mbps}
def get_instance_specs(machine_type, provider='aws-ec2'):
    resource_capacity = {
        't1.nano':     {'CPU': 1,  'DISK': 0,   'NET': 0},
        't2.micro':    {'CPU': 1,  'DISK': 0,   'NET': 0},
        't2.small':    {'CPU': 1,  'DISK': 0,   'NET': 0},
        't2.medium':   {'CPU': 2,  'DISK': 0,   'NET': 0},
        't2.large':    {'CPU': 2,  'DISK': 0,   'NET': 0},
        't2.xlarge':   {'CPU': 4,  'DISK': 0,   'NET': 0},
        't2.2xlarge':  {'CPU': 8,  'DISK': 0,   'NET': 0},
        'm1.small':    {'CPU': 1,  'DISK': 0,   'NET': 0},
        'm1.medium':   {'CPU': 1,  'DISK': 0,   'NET': 0},
        'm1.large':    {'CPU': 2,  'DISK': 0,   'NET': 0},
        'm1.xlarge':   {'CPU': 4,  'DISK': 0,   'NET': 0},
        'm2.xlarge':   {'CPU': 2,  'DISK': 0,   'NET': 0},
        'm2.2xlarge':  {'CPU': 4,  'DISK': 0,   'NET': 0},
        'm2.4xlarge':  {'CPU': 8,  'DISK': 0,   'NET': 0},
        'm3.medium':   {'CPU': 1,  'DISK': 0,   'NET': 0,    'RAM': 3.75, 'STORAGE': '1 x 4 SSD'},
        'm3.large':    {'CPU': 1,  'DISK': 0,   'NET': 0,    'RAM': 7.5,  'STORAGE': '1 x 32 SSD'},
        'm3.xlarge':   {'CPU': 2,  'DISK': 0,   'NET': 0,    'RAM': 15,   'STORAGE': '2 x 40 SSD'},
        'm3.2xlarge':  {'CPU': 4,  'DISK': 0,   'NET': 0,    'RAM': 30,   'STORAGE': '2 x 40 SSD'},
        'm4.large':    {'CPU': 1,  'DISK': 71,  'NET': 450,  'RAM': 8,    'STORAGE': 'ebsonly'},
        'm4.xlarge':   {'CPU': 2,  'DISK': 119, 'NET': 750,  'RAM': 16,   'STORAGE': 'ebsonly'},
        'm4.2xlarge':  {'CPU': 4,  'DISK': 159, 'NET': 1000, 'RAM': 32,   'STORAGE': 'ebsonly'},
        'm4.4xlarge':  {'CPU': 8,  'DISK': 174, 'NET': 2000, 'RAM': 64,   'STORAGE': 'ebsonly'},
        'm4.10xlarge': {'CPU': 20, 'DISK': 174, 'NET': 4000, 'RAM': 160,  'STORAGE': 'ebsonly'},
        'm4.16xlarge': {'CPU': 32, 'DISK': 174, 'NET': 4700, 'RAM': 256,  'STORAGE': 'ebsonly'},
        'c1.medium':   {'CPU': 2,  'DISK': 0,   'NET': 0},
        'c1.xlarge':   {'CPU': 8,  'DISK': 0,   'NET': 0},
        'cc2.8xlarge': {'CPU': 16, 'DISK': 0,   'NET': 0},
        'cg1.4xlarge': {'CPU': 8,  'DISK': 0,   'NET': 0}, 
        'cr1.8xlarge': {'CPU': 16, 'DISK': 0,   'NET': 0},
        'c3.large':    {'CPU': 1,  'DISK': 0,   'NET': 0,    'RAM': 3.75, 'STORAGE': '2 x 16 SSD'},
        'c3.xlarge':   {'CPU': 2,  'DISK': 0,   'NET': 0,    'RAM': 7.5,  'STORAGE': '2 x 40 SSD'},
        'c3.2xlarge':  {'CPU': 4,  'DISK': 0,   'NET': 0,    'RAM': 15,   'STORAGE': '2 x 80 SSD'},
        'c3.4xlarge':  {'CPU': 8,  'DISK': 0,   'NET': 0,    'RAM': 30,   'STORAGE': '2 x 160 SSD'},
        'c3.8xlarge':  {'CPU': 16, 'DISK': 0,   'NET': 0,    'RAM': 60,   'STORAGE': '2 x 320 SSD'},
        'c4.large':    {'CPU': 1,  'DISK': 80,  'NET': 725,  'RAM': 3.75, 'STORAGE': 'ebsonly'},
        'c4.xlarge':   {'CPU': 2,  'DISK': 119, 'NET': 870,  'RAM': 7.5,  'STORAGE': 'ebsonly'},
        'c4.2xlarge':  {'CPU': 4,  'DISK': 158, 'NET': 2300, 'RAM': 15,   'STORAGE': 'ebsonly'},
        'c4.4xlarge':  {'CPU': 8,  'DISK': 174, 'NET': 3900, 'RAM': 30,   'STORAGE': 'ebsonly'},
        'c4.8xlarge':  {'CPU': 18, 'DISK': 174, 'NET': 4000, 'RAM': 60,   'STORAGE': 'ebsonly'},
        'hi1.4xlarge': {'CPU': 8,  'DISK': 0,   'NET': 0},
        'hs1.8xlarge': {'CPU': 8,  'DISK': 0,   'NET': 0},
        'g3.4xlarge':  {'CPU': 8,  'DISK': 0,   'NET': 0},
        'g3.8xlarge':  {'CPU': 16, 'DISK': 0,   'NET': 0},
        'g3.16xlarge': {'CPU': 32, 'DISK': 0,   'NET': 0},
        'g2.2xlarge':  {'CPU': 16, 'DISK': 0,   'NET': 0},
        'x1.16xlarge': {'CPU': 32, 'DISK': 0,   'NET': 0},
        'x1.32xlarge': {'CPU': 64, 'DISK': 0,   'NET': 0},
        'r4.large':    {'CPU': 1,  'DISK': 0,   'NET': 0},
        'r4.xlarge':   {'CPU': 2 , 'DISK': 0,   'NET': 0},
        'r4.2xlarge':  {'CPU': 4,  'DISK': 0,   'NET': 0},
        'r4.4xlarge':  {'CPU': 8,  'DISK': 0,   'NET': 0},
        'r4.8xlarge':  {'CPU': 16, 'DISK': 0,   'NET': 0},
        'r4.16xlarge': {'CPU': 32, 'DISK': 0,   'NET': 0},
        'r3.large':    {'CPU': 1,  'DISK': 0,   'NET': 0,    'RAM': 15,   'STORAGE': '1 x 32 SSD'},
        'r3.xlarge':   {'CPU': 2,  'DISK': 0,   'NET': 0,    'RAM': 30.5, 'STORAGE': '1 x 80 SSD'},
        'r3.2xlarge':  {'CPU': 4,  'DISK': 0,   'NET': 0,    'RAM': 61,   'STORAGE': '1 x 160 SSD'},
        'r3.4xlarge':  {'CPU': 8,  'DISK': 0,   'NET': 0,    'RAM': 122,  'STORAGE': '1 x 320 SSD'},
        'r3.8xlarge':  {'CPU': 16, 'DISK': 0,   'NET': 0,    'RAM': 244,  'STORAGE': '2 x 320 SSD'},
        'p2.xlarge':   {'CPU': 2,  'DISK': 0,   'NET': 0},
        'p2.8xlarge':  {'CPU': 16, 'DISK': 0,   'NET': 0},
        'p2.16xlarge': {'CPU': 32, 'DISK': 0,   'NET': 0},
        'i3.large':    {'CPU': 1,  'DISK': 0,   'NET': 0},
        'i3.xlarge':   {'CPU': 2,  'DISK': 0,   'NET': 0},
        'i3.2xlarge':  {'CPU': 4,  'DISK': 0,   'NET': 0},
        'i3.4xlarge':  {'CPU': 8,  'DISK': 0,   'NET': 0},
        'i3.8xlarge':  {'CPU': 16, 'DISK': 0,   'NET': 0},
        'i3.16xlarge': {'CPU': 32, 'DISK': 0,   'NET': 0},
        'i2.xlarge':   {'CPU': 2,  'DISK': 0,   'NET': 0,    'RAM': 4,  'STORAGE': '1 x 800 SSD'},
        'i2.2xlarge':  {'CPU': 4,  'DISK': 0,   'NET': 0,    'RAM': 8,  'STORAGE': '2 x 800 SSD'},
        'i2.4xlarge':  {'CPU': 8,  'DISK': 0,   'NET': 0,    'RAM': 16, 'STORAGE': '4 x 800'},
        'i2.8xlarge':  {'CPU': 16, 'DISK': 0,   'NET': 0,    'RAM': 32, 'STORAGE': '2 x 800 SSD'},
        'd2.xlarge':   {'CPU': 2,  'DISK': 0,   'NET': 0,    'RAM': 4,  'STORAGE': '3 x 2000 HDD'},
        'd2.2xlarge':  {'CPU': 4,  'DISK': 0,   'NET': 0,    'RAM': 8,  'STORAGE': '6 x 2000 HDD'},
        'd2.4xlarge':  {'CPU': 8,  'DISK': 0,   'NET': 0,    'RAM': 16, 'STORAGE': '12 x 2000 HDD'},
        'd2.8xlarge':  {'CPU': 18, 'DISK': 0,   'NET': 0,    'RAM': 36, 'STORAGE': '24 x 2000 HDD'}
    }    
    return resource_capacity[machine_type]

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
            if service in vm_to_service:
                vm_to_service[vm_ip].append(service)
            else:
                vm_to_service[vm_ip] = [service]
        remote_exec.close_client(ssh_client)
    return vm_to_service
