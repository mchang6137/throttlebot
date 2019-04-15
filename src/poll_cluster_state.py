import subprocess
import remote_execution as remote_exec
from kubernetes import client, config
import yaml
import os
import math
import traceback

'''
Queries information about the cluster directly from the true state
Currently retrieves the information from quilt ps

CURRENT IMPL: Retrieve data from naive calls of quilt ps and docker ps
TODO: Retrieve the information from directly querying the Quilt key-value store

'''

### Pre-defined blacklist (Temporary)
quilt_blacklist = ['quilt/ovs', 'google/cadvisor:v0.24.1', 'quay.io/coreos/etcd:v3.0.2', 'mchang6137/quilt:latest',
                   'throttlebot/quilt:latest', 'tsaianson/quilt:latest']
service_blacklist = ['hantaowang/lumbersexual', 'hantaowang/hotrod-seed', 'mchang6137/workloadlb', 'mchang6137/workloadmean', 'workloadlb', 'workloadmean', 'hotrodworkload', 'hotrodworkloadlb', 'mchang6137/hotrodworkload', 'mchang6137/hotrodworkloadlb']
testing_blacklist = ['hantaowang/logstash-postgres', 'haproxy:1.7','elasticsearch:2.4', 'kibana:4', 'library/postgres:9.4',
                     'mysql:5.6.32', 'osalpekar/spark-image-compress...']

#config.load_kube_config()

#v1 = client.CoreV1Api()
#v1_beta = client.ExtensionsV1beta1Api()

# Find all the VMs in the current Quilt Cluster
# Returns a list of IP addresses
def get_actual_vms(orchestrator='quilt'):
    if orchestrator == 'quilt':
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
    else:
        return [pod.status.pod_ip for pod in v1.list_pod_for_all_namespaces().items if
                pod.metadata.namespace == "default"]

# If workload is being generated from multiple pods, automatically query the IP
# addresses of the pods and container IDs
def get_workload_gen_pods():
    vm_ips = get_actual_vms()
    service_instances = get_service_placements(vm_ip)
    # Change name of the container when ready
    assert 'workload_gen' in service_instances
    return service_instances['workload_gen']

def get_master(orchestrator='quilt'):
    if orchestrator == 'quilt':
        ps_args = ['quilt', 'ps']
        awk_args = ["awk", r'{print $6}']
        #Identify the machine index of the master node
        machine_roles = parse_quilt_ps_col(2, machine_level=True)

        # Get the IP addresses of all the machines
        machine_ips = parse_quilt_ps_col(6, machine_level=True)

        combined_machine_info = zip(machine_roles, machine_ips)
        ips = []
        for info in combined_machine_info:
            role,ip = info
            if role == 'Master':
                return ip
    else:
        nodes = [(node.metadata.labels['kubernetes.io/role'], node.metadata.name) for node in v1.list_node().items]

        name = ""
        for node in nodes:
            if (node[0] == 'master'):
                name = node[1]

        master_node_ip = v1.read_node(name).status.addresses[1].address

        return master_node_ip

# Gets all the services in the Quilt cluster
# Identifies the services based on the COMMAND
def get_actual_services(orchestrator='quilt'):
    if orchestrator == 'quilt':
        services = parse_quilt_ps_col(3, machine_level=False)
        return services
    else:
        return [service.metadata.name for service in v1.list_service_for_all_namespaces().items]

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
    return quilt_blacklist + service_blacklist

# Returns all stressable resources available for this
def get_stressable_resources(cloud_provider='aws-ec2'):
    all_resources = ['CPU-CORE', 'CPU-QUOTA', 'NET', 'DISK', 'MEMORY']
    return all_resources

# Identify the container id and VM where a service might be residing
# Return service_name -> (vm_ip, container_id)
def get_service_placements(vm_ips, orchestrator='quilt'):
    if orchestrator == 'quilt':
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
                if service_name == 'postgres:9.4':
                    service_name = 'library/postgres:9.4'
                if service_name == 'osalpekar/spark-image-compressor':
                    service_name = 'osalpekar/spark-image-compress...'
                if service_name not in service_to_deployment:
                    service_to_deployment[service_name] = [identifier_tuple]
                else:
                    service_to_deployment[service_name].append(identifier_tuple)
            remote_exec.close_client(ssh_client)
        return service_to_deployment

    # Else using Kubernetes
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


# Identify the services residing on each VM
def get_vm_to_service(vm_ips, orchestrator='quilt'):
    if orchestrator == 'quilt':
        vm_to_service = {}
        for vm_ip in vm_ips:
            ssh_client = remote_exec.get_client(vm_ip)
            docker_container_id_cmd = 'docker ps | tr -s \' \' | cut -d \' \' -f1 | tail -n +2'
            docker_container_image_cmd = 'docker ps | tr -s \' \' | cut -d \' \' -f2 | tail -n +2'
            _, stdout1, _ = ssh_client.exec_command(docker_container_image_cmd)
            service_names = stdout1.read().splitlines()

            #Assume that the container ids and the service names are ordered in the same way
            for service in service_names:
                if service == 'osalpekar/spark-image-compressor':
                    service = 'osalpekar/spark-image-compress...'
                if service in quilt_blacklist or service in service_blacklist:
                    continue
                if vm_ip in vm_to_service:
                    vm_to_service[vm_ip].append(service)
                else:
                    vm_to_service[vm_ip] = [service]
            remote_exec.close_client(ssh_client)
        return vm_to_service

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

def get_deployment_cpu_quota(deployment_name):
    time =  v1_beta.read_namespaced_deployment(namespace="default", name=deployment_name).spec.template.spec.containers[
        0].resources.requests['cpu']

    if time[-1] == "m":
        return float(time[:-1]) / 1000


    return (float(time))



def create_and_deploy_workload_pod(name, num_requests, concurrency, hostname, port, additional_args):

    body = yaml.load(
        open(
            os.path.join(os.getcwd(),
            'workload.yaml')))

    args = populate_workload_args(num_requests, concurrency, hostname, port, additional_args)

    body['spec']['containers'][0]['args'] = args
    body['metadata']['name'] = name

    v1.create_namespaced_pod(body=body, namespace='default')



def create_and_deploy_workload_deployment(name, replicas, num_requests, concurrency, hostname, port, thread_count, connection_count, test_length,
                                          additional_args, node_count, ab=True):

    body = yaml.load(
        open(
            os.path.join(os.getcwd() + "/manifests/",
            'workload_deployment.yaml')))

    args = populate_workload_args(num_requests, concurrency, hostname, port, thread_count, connection_count, test_length,
                                  additional_args, ab=ab)

    body['spec']['template']['spec']['containers'][0]['args'] = args
    body['metadata']['name'] = name
    body['spec']['replicas'] = replicas
    body['metadata']['labels']['app'] = name
    body['spec']['template']['metadata']['labels']['app'] = name
    body['spec']['selector']['matchLabels']['app'] = name
    body['spec']['template']['spec']['containers'][0]['resources']['limits']['cpu'] = .85

    if ab:
        body['spec']['template']['spec']['containers'][0]['image'] = "rbala19/ab"
    else:
        body['spec']['template']['spec']['containers'][0]['image'] = "rbala19/wrk"

    remove_node_labels = subprocess.check_output("kubectl label nodes --all nodetype-", shell=True)

    nodes = [node.metadata.name for node in v1.list_node().items if
             node.metadata.labels['kubernetes.io/role'] == "node"]

    for i in range(node_count + 1):
        output = subprocess.check_output("kubectl label nodes {} nodetype=workload".format(nodes[i]), shell=True)

    for i in range(node_count + 1, len(nodes)):
        output = subprocess.check_output("kubectl label nodes {} nodetype=service".format(nodes[i]), shell=True)

    v1_beta.create_namespaced_deployment(body=body, namespace='default')

def label_all_unlabeled_nodes_as_service():
    all_nodes = [node.metadata.name for node in v1.list_node().items if
             node.metadata.labels['kubernetes.io/role'] == "node"]

    worker_nodes = subprocess.check_output("kubectl get nodes -l nodetype=workload | awk {\'print $1 \'}", shell=True).decode("utf-8").split("\n")[1:-1]

    nodes_to_label = [node for node in all_nodes if node not in worker_nodes]


    for node in nodes_to_label:

        try:
            output = subprocess.check_output("kubectl label nodes {} nodetype=service --overwrite".format(node), shell=True)

        except:
            traceback.print_exc()

def ensure_workload_node_count(node_count):
    output = subprocess.check_output("kubectl get nodes -l nodetype=workload | awk {\'print $1\'}", shell=True).decode(
        "utf-8").split("\n")
    if len(output) > 1:
        node_names = output[1:-1]
        if len(node_names) < node_count - 1:
            nodes = [node.metadata.name for node in v1.list_node().items if
                 node.metadata.labels['kubernetes.io/role'] == "node"]
            nodes = [node for node in nodes if node not in node_names]
            for i in range(node_count - 1 - len(node_names)):
                output = subprocess.check_output("kubectl label nodes {} nodetype=workload".format(nodes[i]),
                                                 shell=True)
    else:
        nodes = [node.metadata.name for node in v1.list_node().items if
                 node.metadata.labels['kubernetes.io/role'] == "node"]
        for i in range(node_count - 1):
            output = subprocess.check_output("kubectl label nodes {} nodetype=workload".format(nodes[i]),
                                             shell=True)


def create_scale_deployment(name, cpu_cost):

    body = yaml.load(
        open(
            os.path.join(os.getcwd() + "/manifests/",
            '{}.yaml'.format(name))))

    body['spec']['template']['spec']['containers'][0]['resources']['requests']['cpu'] = cpu_cost
    body['spec']['template']['spec']['containers'][0]['resources']['limits']['cpu'] = cpu_cost
    v1_beta.create_namespaced_deployment(body=body, namespace='default')

def get_all_pods_from_deployment(deployment_name, label = None, safe = False):

    if safe:
        lists = subprocess.check_output("kubectl get pods | grep \'" + deployment_name + "\'", shell=True) \
                    .decode('utf-8').split("\n")[:-1]

        lists2 = []
        for l in lists:
            lists2.append(l.split(" "))

        pods = [l[0] for l in lists2 if "Running" in l]

        return pods

    else:

        selector = deployment_name
        if label:
            selector = label

        return [pod.metadata.name for pod in v1.list_namespaced_pod(namespace="default",
                                                         label_selector='app={}'.format(selector)).items]



def populate_workload_args(num_requests, concurrency, hostname, port, thread_count, connection_count, test_length,
                           additional_args, ab = True):

    if ab:
        args = ["-c",
                'while true; do ab -r -n {} -c {} -p post.json -T application/json -s 200 -q http://{}:{}/{}/; sleep 1; done;'.format(
                    num_requests, concurrency, hostname, port, additional_args
                )]
    else:
        args = ["-c",
                'while true; do wrk -t{} -c{} -d{}s -s post.sh --latency http://{}:{}/{}/; done;'.format(
                    thread_count, connection_count, test_length, hostname, port, additional_args
                )]


    return args

def delete_workload_pod(name):
    v1.delete_namespaced_pod(
        namespace='default', name=name)

def get_node_capacity():

    nodes = [node.metadata.name for node in v1.list_node().items if node.metadata.labels['kubernetes.io/role'] == "node"]

    return int(subprocess.check_output(
        "kubectl describe node {}".format(nodes[0]) + "| grep -C 2 \'Capacity\' | grep \'cpu\' | awk {\'print $2 \'}",
        shell=True).decode('utf-8')[:-1])


def delete_workload_deployment(name):
    v1_beta.delete_namespaced_deployment(namespace='default', name=name)
