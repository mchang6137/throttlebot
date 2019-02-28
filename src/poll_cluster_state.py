import subprocess
import remote_execution as remote_exec
from kubernetes import client, config
import yaml
import os

'''
Queries information about the cluster directly from the true state
Currently retrieves the information from quilt ps

CURRENT IMPL: Retrieve data from naive calls of quilt ps and docker ps
TODO: Retrieve the information from directly querying the Quilt key-value store

'''

### Pre-defined blacklist (Temporary)
quilt_blacklist = ['quilt/ovs', 'google/cadvisor:v0.24.1', 'quay.io/coreos/etcd:v3.0.2', 'mchang6137/quilt:latest',
                   'throttlebot/quilt:latest', 'tsaianson/quilt:latest']
service_blacklist = ['hantaowang/lumbersexual', 'hantaowang/hotrod-seed']
testing_blacklist = ['hantaowang/logstash-postgres', 'haproxy:1.7','elasticsearch:2.4', 'kibana:4', 'library/postgres:9.4',
                     'mysql:5.6.32', 'osalpekar/spark-image-compress...']

config.load_kube_config()

v1 = client.CoreV1Api()

# Find all the VMs in the current Quilt Cluster
# Returns a list of IP addresses
def get_actual_vms():
    # ps_args = ['quilt', 'ps']
    # awk_args = ["awk", r'{print $6}']
    #
    # # Identify the machine index of the master node
    # machine_roles = parse_quilt_ps_col(2, machine_level=True)
    #
    # # Get the IP addresses of all the machines
    # machine_ips = parse_quilt_ps_col(6, machine_level=True)
    #
    # combined_machine_info = zip(machine_roles, machine_ips)
    # ips = []
    # for info in combined_machine_info:
    #     role,ip = info
    #     if role == 'Master':
    #         continue
    #     ips.append(ip)
    # return ips

    return [pod.status.pod_ip for pod in v1.list_pod_for_all_namespaces().items if
     pod.metadata.namespace == "default"]



def get_master():
    # ps_args = ['quilt', 'ps']
    # awk_args = ["awk", r'{print $6}']
    # # Identify the machine index of the master node
    # machine_roles = parse_quilt_ps_col(2, machine_level=True)
    #
    # # Get the IP addresses of all the machines
    # machine_ips = parse_quilt_ps_col(6, machine_level=True)
    #
    # combined_machine_info = zip(machine_roles, machine_ips)
    # ips = []
    # for info in combined_machine_info:
    #     role,ip = info
    #     if role == 'Master':
    #         return ip

    nodes = [(node.metadata.labels['kubernetes.io/role'], node.metadata.name) for node in v1.list_node().items]

    name = ""
    for node in nodes:
        if (node[0] == 'master'):
            name = node[1]

    master_node_ip = v1.read_node(name).status.addresses[1]

    return master_node_ip



# Gets all the services in the Quilt cluster
# Identifies the services based on the COMMAND
def get_actual_services():
    # services = parse_quilt_ps_col(3, machine_level=False)
    # return services

    return [service.metadata.name for service in v1.list_service_for_all_namespaces().items]
# return services.items

def get_service_ip(service_name):
    return v1.read_namespaced_service(service_name, namespace="default").spec.cluster_ip


def get_service_port(service_name):
    return v1.read_namespaced_service(service_name, namespace="default").spec.ports[0].port


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
    # return quilt_blacklist + service_blacklist + testing_blacklist
    return quilt_blacklist + service_blacklist

# Returns all stressable resources available for this
def get_stressable_resources(cloud_provider='aws-ec2'):
    all_resources = ['CPU-CORE', 'CPU-QUOTA', 'NET', 'DISK', 'MEMORY']
    return all_resources

# Identify the container id and VM where a service might be residing
# Return service_name -> (vm_ip, container_id)
def get_service_placements(vm_ips):
    # service_to_deployment = {}
    # for vm_ip in vm_ips:
    #     ssh_client = remote_exec.get_client(vm_ip)
    #     docker_container_id_cmd = 'docker ps | tr -s \' \' | cut -d \' \' -f1 | tail -n +2'
    #     docker_container_image_cmd = 'docker ps | tr -s \' \' | cut -d \' \' -f2 | tail -n +2'
    #     _, stdout1, _ = ssh_client.exec_command(docker_container_id_cmd)
    #     container_ids = stdout1.read().splitlines()
    #     _, stdout2, _ = ssh_client.exec_command(docker_container_image_cmd)
    #     service_names = stdout2.read().splitlines()
    #
    #     zipped_name_id = zip(service_names, container_ids)
    #
    #     #Assume that the container ids and the service names are ordered in the same way
    #     for service_name, container_id in zipped_name_id:
    #         if service_name[-4:] == '.git':
    #             service_name = service_name[service_name.index('/')+1:]
    #         identifier_tuple = (vm_ip, container_id)
    #         if service_name == 'postgres:9.4':
    #             service_name = 'library/postgres:9.4'
    #         if service_name == 'osalpekar/spark-image-compressor':
    #             service_name = 'osalpekar/spark-image-compress...'
    #         if service_name not in service_to_deployment:
    #             service_to_deployment[service_name] = [identifier_tuple]
    #         else:
    #             service_to_deployment[service_name].append(identifier_tuple)
    #     remote_exec.close_client(ssh_client)
    # return service_to_deployment

    pods = v1.list_namespaced_pod("default").items

    port_to_pod = {}
    vm_ip_numbers = vm_ips



    for pod in pods:
        index = -1
        if pod.status.pod_ip in vm_ip_numbers:
            index = vm_ip_numbers.index(pod.status.pod_ip)
        if index != -1:
            for container in pod.spec.containers:
                if container.ports:
                    for port_info in container.ports:
                        port_to_pod[port_info.container_port] = [vm_ips[index], container.name]

    service_to_vm = {}

    # For every service port, check if a service shares a port with any vms

    all_services = v1.list_service_for_all_namespaces().items
    for service in all_services:
        service_name = service.metadata.name
        if service_name[-4:] == '.git':
            service_name = service_name[service_name.index('/') + 1:]
        if service_name == 'postgres:9.4':
            service_name = 'library/postgres:9.4'
        if service_name == 'osalpekar/spark-image-compressor':
            service_name = 'osalpekar/spark-image-compress...'
        for port_info in service.spec.ports:
            if port_info.port not in port_to_pod:
                continue
            if service_name not in service_to_vm:
                service_to_vm[service_name] = [port_to_pod[port_info.port]]
            else:
                service_to_vm[service_name].append(port_to_pod[port_info.port])

    return service_to_vm


# return self._k8s_v1.list_namespaced_pod(
#                 namespace='default',
#                 label_selector=CLIPPER_DOCKER_LABEL).items:

# Identify the services residing on each VM
def get_vm_to_service(vm_ips):


    endpoint_list = v1.list_namespaced_endpoints("default").items

    vm_ip_numbers = vm_ips

    vm_to_service = {}

    port_to_service = {}

    # For every service port, map that port to service_name 
    all_services = v1.list_service_for_all_namespaces().items
    for service in all_services:
        service_name = service.metadata.name
        if service_name == 'osalpekar/spark-image-compressor':
            service_name = 'osalpekar/spark-image-compress...'
        if service_name in quilt_blacklist or service_name in service_blacklist:
            continue
        for port_info in service.spec.ports:
            port_to_service[port_info.port] = service_name


    #For every endpoint (exposed pod), look up to see if its ports are shared with a service
    for endpoint in endpoint_list:
        for subset in endpoint.subsets:
            for address in subset.addresses:
                index = -1
                if address.ip in vm_ip_numbers:
                    index = vm_ip_numbers.index(address.ip)
                if index != -1:
                    for port_info in subset.ports:
                        port_number = port_info.port
                        if port_number not in port_to_service:
                            continue
                        if vm_ip_numbers[index] not in vm_to_service:
                            vm_to_service[vm_ip_numbers[index]] = [port_to_service[port_number]]
                        else:
                            vm_to_service[vm_ip_numbers[index]].append(port_to_service[port_number])

    return vm_to_service

def create_and_deploy_workload_pod(name, num_requests, concurrency, hostname, port, additional_args):

    body = yaml.load(
        open(
            os.path.join(os.getcwd(),
            'workload.yaml')))

    args = []
    args.append("-n {}".format(num_requests))
    args.append("-c {}".format(concurrency))
    args.append("-p post.json")
    args.append("-T application/json")
    args.append("-s 200")
    args.append("-q")
    args.append("-e results_file")
    args.append("http://{}:{}/{}/".format(hostname, port, additional_args))


    body['spec']['containers'][0]['args'] = args
    body['metadata']['name'] = name

    v1.create_namespaced_pod(body=body, namespace='default')

def delete_workload_pod(name):
    v1.delete_namespaced_pod(
        namespace='default', name=name)