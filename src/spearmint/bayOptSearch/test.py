import subprocess
import shlex
from collections import defaultdict
import sys
sys.path.append("/Users/rahulbalakrishnan/Desktop/throttlebot/src")
import modify_resources as resource_modifier
import run_experiment
import filter_policy, instance_specs
import remote_execution as re
from mr import MR
from collections import defaultdict



def ip_toservices():
    service_names = ["elasticsearch", "kibana", "logstash", "mysql", "postgres", "node-apt-app", "haproxy"]

    output = str(subprocess.check_output("quilt ps | grep \'Amazon\' | awk {\'print $6\'}", shell=True).decode("utf-8"))
    output = output.split('\n')
    ips = output[:-1]
    # print(ips)

    output = str(subprocess.check_output("quilt ps | grep \'Amazon\' | awk {\'print $1\'}", shell=True).decode("utf-8"))
    output = output.split('\n')
    machines = output[:-1]
    # print(machines)

    machine_to_ip = {}
    for index in range(len(machines)):
        machine_to_ip[machines[index]] = ips[index]



    output = str(subprocess.check_output("quilt ps | grep \'running\' | awk {\'print $3\'}", shell=True).decode("utf-8"))
    output = output.split('\n')
    services = output[:-1]
    print(services)

    output = str(subprocess.check_output("quilt ps | grep \'running\' | awk {\'print $2\'}", shell=True).decode("utf-8"))
    output = output.split('\n')
    machines = output[:-1]
    print(machines)

    machines_to_services = defaultdict(list)

    for index in range(len(machines)):
        machine = machines[index]
        service_name = services[index]
        services_matched = []
        for service in service_names:

            if service in service_name:
                services_matched.append(service)
        earliest_service = min(services_matched, key = service_name.index)
        machines_to_services[machine].append(earliest_service)

    ip_to_services = {}
    for machine in machines_to_services:
        key_name = machine_to_ip[machine]
        value = machines_to_services[machine]
        ip_to_services[key_name] = value

    print(ip_to_services)

def master_node():
    master_node = str(subprocess.check_output("quilt ps | grep Master | awk {\'print $6\'}", shell=True).decode("utf-8"))[:-1]
    print(master_node)


def docker_test(machine, service):
    client = re.get_client(machine)
    _, containers, _ = client.exec_command("docker ps | grep " + service + " | awk {'print $1'}")
    containers = containers.read().split("\n")
    print(containers)
import subprocess
import shlex
from collections import defaultdict
import sys
sys.path.append("/Users/rahulbalakrishnan/Desktop/throttlebot/src")
import modify_resources as resource_modifier
import run_experiment
import filter_policy, instance_specs
import remote_execution as re
from mr import MR
from collections import defaultdict



def ip_toservices():
    service_names = ["elasticsearch", "kibana", "logstash", "mysql", "postgres", "node-apt-app", "haproxy"]

    output = str(subprocess.check_output("quilt ps | grep \'Amazon\' | awk {\'print $6\'}", shell=True).decode("utf-8"))
    output = output.split('\n')
    ips = output[:-1]
    # print(ips)

    output = str(subprocess.check_output("quilt ps | grep \'Amazon\' | awk {\'print $1\'}", shell=True).decode("utf-8"))
    output = output.split('\n')
    machines = output[:-1]
    # print(machines)

    machine_to_ip = {}
    for index in range(len(machines)):
        machine_to_ip[machines[index]] = ips[index]



    output = str(subprocess.check_output("quilt ps | grep \'running\' | awk {\'print $3\'}", shell=True).decode("utf-8"))
    output = output.split('\n')
    services = output[:-1]
    print(services)

    output = str(subprocess.check_output("quilt ps | grep \'running\' | awk {\'print $2\'}", shell=True).decode("utf-8"))
    output = output.split('\n')
    machines = output[:-1]
    print(machines)

    machines_to_services = defaultdict(list)

    for index in range(len(machines)):
        machine = machines[index]
        service_name = services[index]
        services_matched = []
        for service in service_names:

            if service in service_name:
                services_matched.append(service)
        earliest_service = min(services_matched, key = service_name.index)
        machines_to_services[machine].append(earliest_service)

    ip_to_services = {}
    for machine in machines_to_services:
        key_name = machine_to_ip[machine]
        value = machines_to_services[machine]
        ip_to_services[key_name] = value

    print(ip_to_services)

def master_node():
    master_node = str(subprocess.check_output("quilt ps | grep Master | awk {\'print $6\'}", shell=True).decode("utf-8"))[:-1]
    print(master_node)


def docker_test(machine, service):
    client = re.get_client(machine)
    _, containers, _ = client.exec_command("docker ps | grep " + service + " | awk {'print $1'}")
    containers = containers.read().split("\n")
    print(containers)

docker_test("54.67.2.116", "kibana")


