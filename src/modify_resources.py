import argparse
import paramiko
import re
from subprocess import Popen, PIPE
import sys
from time import sleep

import threading

from weighting_conversions import *
from remote_execution import *
from measure_utilization import *
from container_information import *
from max_resource_capacity import *


quilt_machines = ("quilt", "ps")

connected_pattern = re.compile(".+Connected}$")
ip_pattern = r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'

#Container blacklist for container names whose placements should not move
container_blacklist = ['ovn-controller', 'minion', 'ovs-vswitchd', 'ovsdb-server', 'etcd']

# Conversion factor from unit KEY to KiB
CONVERSION = {"KiB": 1, "MiB": 2**10, "GiB": 2**20}

# The name of the container that runs an infinite loop just to consume CPU.
CPU_EATER = "cpu_eater"

#This is changed manually
MAX_NETWORK_BANDWIDTH=600

'''Stressing the Network'''

#Add a Network Delay to each of the container interfaces on each machine
def set_network_delay(ssh_client, delay):
    if delay <= 0: 
        invalid_resource_parameter('Network Delay', delay)
        return
    container_ids = get_container_id(ssh_client, full_id=False, append_c=True)
    for container in container_ids:
        cmd = "sudo tc qdisc add dev {} root netem delay {}ms".format(container, delay)
        #Not all containers will have an exposed interface but the ones which do not will simply fail
        response = ssh_exec(ssh_client, cmd)

#Contract: Bandwidth must be set in Kb/s
#Fix me! Find the Bandwidth of the machine
#container_to_bandwidth is a map from interface->bandwidth
def set_network_bandwidth(ssh_client, container_to_bandwidth, outgoing_traffic=True):

    # talk to matt about network stuff
    for container in container_to_bandwidth:
        if container_to_bandwidth[container] <= 0:
            bandwidth = container_to_bandwidth[container]
            invalid_resource_parameter("Network Bandwidth", bandwidth)
            return

    for container in container_to_bandwidth:
        bandwidth = int(container_to_bandwidth[container])

                #Temporary!
        container = 'ens3'
        cmd1 = 'sudo tc qdisc add dev {} handle 1: root htb default 11'.format(container)
        cmd2 = 'sudo tc class add dev {} parent 1: classid 1:1 htb rate {}kbit ceil {}kbit'.format(container, bandwidth, bandwidth)
        cmd3 = 'sudo tc class add dev {} parent 1:1 classid 1:11 htb rate {}kbit ceil {}kbit'.format(container, bandwidth, bandwidth)
                #UNNECESSARY BECAUSE MICHAEL IS A FUCKING DUMBASS!!!!
                #cmd4 = 'tc filter add dev {} parent 1: protocol ip u32 match ip dst {} flowid 1:1'.format(container, victim_private_ip)

        ssh_exec(ssh_client, cmd1)
        ssh_exec(ssh_client, cmd2)
        ssh_exec(ssh_client, cmd3)

    return


#Removes all network manipulations for ALL machines in the Quilt Environment
def remove_all_network_manipulation(ssh_client, remove_all_machines=False):
        all_machines = get_all_machines()
        if remove_all_machines is False:
                container_ids = get_container_id(ssh_client, full_id=False, append_c=True)
                for container in container_ids:
                        container = 'ens3'
                        cmd = "sudo tc qdisc del dev {} root".format(container)
                        ssh_exec(ssh_client, cmd)
                        return
        else:
                for machine in all_machines:
                    temp_ssh_client = quilt_ssh(machine)
                    container_ids = get_container_id(temp_ssh_client, full_id=False, append_c=False)
                    for container in container_ids:
                        cmd = "sudo tc qdisc del dev {} root".format(container)
                        ssh_exec(temp_ssh_client, cmd)

'''Stressing the CPU'''
#Indicates the number of 10%-stress that is introduced into the system
def update_cpu_through_stress(ssh_client, num_stress=0):
    """CPU Limit describes how much CPU will be used by the stresser"""
    if num_stress < 0:
        invalid_resource_parameter("CPU Allocation", limit)
        return
        
        #Separate CPU limit into several smaller increments of 10 instead of one larger one
    for x in range(num_stress):
        cmd = "stress -c 1 &> /dev/null & cpulimit -p $( pidof -o $! stress ) -l {} &> /dev/null &".format(10)
        ssh_exec(ssh_client, cmd)

#Allows you to set the CPU periods in a container, intended for a container that is already running
#as opposed to update_cpu which actually just stresses the CPU by a predetermined amount
#Assumes that that CPU_period and CPU_quota were not set beforehand
#CPU period is assumed to be 1 second no matter what
def set_cpu_shares(ssh_client, cpu_quota):
    container_names = get_container_names(ssh_client)
    # cpu_quota = int(cpu_quota * get_num_cores(ssh_client) * 1000000)
    cpu_quota = int((float(cpu_quota) / 10) * 1000000)
    cpu_period = 1000000 #1 second in microseconds

    #CPU Quota must be less than 1 second
    # while cpu_quota > 1000000:
    #         cpu_quota = cpu_quota/2
    #         cpu_period = cpu_period/2

    print 'Adjusted CPU period: {}'.format(cpu_period)
    print 'CPU Quota: {}'.format(cpu_quota)

    throttled_containers = []
    
    core = 0
    for container_name in container_names:
        if container_name not in container_blacklist:
            update_command = 'docker update --cpu-period {} --cpu-quota {} --cpuset-cpus {} {}'.format(cpu_period, cpu_quota, core, container_name)
            print update_command
            ssh_client.exec_command(update_command)
            throttled_containers.append(container_name)
            core += 1
    return throttled_containers

def reset_cpu(ssh_client, cpu_throttle_type):
    if cpu_throttle_type == 'period':
            reset_cpu_shares(ssh_client)
    elif cpu_throttle_type == 'stress':
            reset_cpu_stress(ssh_client)

def reset_cpu_shares(ssh_client):
    container_names = get_container_names(ssh_client)
    cpu_quota = -1

    for container_name in container_names:
        if container_name not in container_blacklist:
            update_command = 'docker update --cpu-quota 0 {}'.format(container_name)
            ssh_client.exec_command(update_command)
    print 'reset_cpu_shares'

def reset_cpu_stress(ssh_client):
    cmd = "killall stress"
    ssh_exec(ssh_client, cmd)
    print 'Cpu Stresses killed'


'''Stressing the Disk Read/write throughput'''

#set_blkio will change the relative proportion of all the containers (proportions range from 0-1000)
def set_blkio(ssh_client, relative_weight, container_id):
    if relative_weight < 10 or relative_weight > 1000:
        invalid_resource_parameters("blkio weight", relative_weight)
        return
    all_containers = get_container_names(ssh_client, only_runner=False)
    cmd = 'docker update --blkio-weight={} {}'.format(relative_weight, container_id)
    ssh_exec(ssh_client, cmd)

#This is a dummy container that eats an arbitrary amount of Disk atthe cost of some CPU utilization
#blkio_weight is a weight that is from 10-1000, which specifies the amount of disk utilization
def create_dummy_blkio_disk_eater(ssh_client, blkio_weight):
    if blkio_weight < 10 or blkio_weight > 1000:
        invalid_resource_parameters("blkio_weight", blkio_weight)
        return
    create_docker_image_cmd = 'docker run -d --blkio-weight {} --name disk_eater ubuntu /bin/sh -c'.format(blkio_weight)
    container_cmd =  '\"while true; do dd if=/dev/zero of=test bs=1048576 count=1024 conv=fsync; done\"'
    ssh_exec(ssh_client, create_docker_image_cmd + container_cmd)

#Positive value to set a maximum for both disk write and disk read
#0 to reset the value
def change_container_blkio(ssh_client, disk_bandwidth):
    container_blacklist = ['ovn-controller', 'etcd', 'ovs-vswitchd', 'ovsdb-server', 'minion']
    all_names = get_container_names(ssh_client)
    for name in all_names:
        if name not in container_blacklist:
            disk_eater_id_cmd = 'docker inspect --format=\"{{{{.Id}}}}\" {}'.format(name)
            print disk_eater_id_cmd
            _, disk_eater_id, _ = ssh_client.exec_command(disk_eater_id_cmd)
            disk_eater_id_temp = disk_eater_id.read()
            disk_eater_id_str = disk_eater_id_temp.strip('\n')

            print disk_eater_id_str
            
            #Set Read and Write Conditions in real-time using cgroups
            #Assumes the other containers default to write to device major number 252 (minor number arbitrary)
            set_cgroup_write_rate_cmd = 'echo \"252:0 {}" | sudo tee /sys/fs/cgroup/blkio/docker/{}/blkio.throttle.write_bps_device'.format(disk_bandwidth, disk_eater_id_str)
            set_cgroup_read_rate_cmd = 'echo \"252:0 {}" | sudo tee /sys/fs/cgroup/blkio/docker/{}/blkio.throttle.read_bps_device'.format(disk_bandwidth, disk_eater_id_str)

            print set_cgroup_write_rate_cmd
            print set_cgroup_read_rate_cmd

            _, stdout, _ = ssh_client.exec_command(set_cgroup_write_rate_cmd)
            _, stdout, _ = ssh_client.exec_command(set_cgroup_read_rate_cmd)
                        
        #Sleep 10 seconds since the current queue must be emptied before this can be fulfilled
    sleep(10)
    return 0

#Sets the maximum read and write rate of the disk to bandwidth_maximum
#Unfortunately, we cannot set the block io because AWS guest machines only use noop I/O scheduling
#disk_bandwidth should be in Kilobytes/sec
def create_dummy_disk_eater(ssh_client, disk_bandwidth):
    if disk_bandwidth < 0:
            invalid_resource_parameters("Disk_bandwidth", disk_bandwidth)
            return

    max_bandwidth = get_disk_capabilities(ssh_client, 100)
    num_full_bandwidth = disk_bandwidth/max_bandwidth
    partial_bandwidth = disk_bandwidth % max_bandwidth
    print 'Number of full disk bandwidth is {}'.format(num_full_bandwidth)
    print 'Disk eater partial bandwidth is {}'.format(partial_bandwidth)

    container_cmd_initialize = '\"dd if=/dev/zero of=test bs=1048576 count=1024 iflag=nocache oflag=dsync;'
    container_cmd =  'while true; do dd if=test of=test1 bs=1048576 count=1024 iflag=nocache oflag=dsync; done\"'
    
    for x in range(num_full_bandwidth):
            create_docker_image_cmd = 'docker run -d --name disk_eater_{} ubuntu /bin/bash -c '.format(x)
            _, stdout, _ = ssh_client.exec_command(create_docker_image_cmd + container_cmd_initialize + container_cmd)

    create_docker_image_cmd = 'docker run -d --name disk_eater ubuntu /bin/bash -c '
    _, stdout, _ = ssh_client.exec_command(create_docker_image_cmd + container_cmd_initialize + container_cmd)

    #Need some time to sleep so that the container has time to finish spinning up making the initial copy
    sleep(30)
    disk_eater_id_cmd = 'docker inspect --format=\"{{.Id}}\" disk_eater'

    _, disk_eater_id, _ = ssh_client.exec_command(disk_eater_id_cmd)
    disk_eater_id_temp = disk_eater_id.read()
    disk_eater_id_str = disk_eater_id_temp.strip('\n')

    #Set Read and Write Conditions in real-time using cgroups
    #Assumes the other containers default to write to device major number 252 (minor number arbitrary)
    set_cgroup_write_rate_cmd = 'echo \"252:0 {}" | sudo tee /sys/fs/cgroup/blkio/docker/{}/blkio.throttle.write_bps_device'.format(partial_bandwidth, disk_eater_id_str)
    set_cgroup_read_rate_cmd = 'echo \"252:0 {}" | sudo tee /sys/fs/cgroup/blkio/docker/{}/blkio.throttle.read_bps_device'.format(partial_bandwidth, disk_eater_id_str)
    
    _, stdout, _ = ssh_client.exec_command(set_cgroup_write_rate_cmd)
    _, stdout, _ = ssh_client.exec_command(set_cgroup_read_rate_cmd)

    return num_full_bandwidth
        
#Removes the disk eater from the picture
def remove_dummy_disk_eater(ssh_client, num_full):
    #Remove the container
    for x in range(num_full):
        kill_container_cmd = 'docker rm -f disk_eater_{}'.format(x)
        ssh_exec(ssh_client, kill_container_cmd)
    #Kills the partial container as well
    kill_container_cmd = 'docker rm -f disk_eater'
    ssh_exec(ssh_client, kill_container_cmd)

'''Helper functions that are used for various reasons'''

def convert_to_kib(mem):
    """MEM is a tuple (mem_size, unit). Unit must be KiB, MiB, or GiB.
    Returns mem_size converted to KiB."""
    mem_size, unit = mem
    multiplier = CONVERSION[unit]
    return mem_size * multiplier

def matches_ip(line, ip):
    m = re.search(ip_pattern, line)
    return m.group(0) == ip


def is_connected(line):
    line = line.strip()
    return connected_pattern.match(line)


def check_valid_ip(vm_ip):
    p = Popen(quilt_machines, stdout=PIPE)
    lines = p.stdout.read().splitlines()
    matched = False

    for line in lines:
        if not matches_ip(line, vm_ip):
            continue
        if not is_connected(line):
            sys.exit("The VM ({}) is not connected".format(vm_ip))
        matched = True
        break

    if not matched:
        sys.exit("There is no VM with public IP {}".format(vm_ip))

def get_all_machines():
    all_machines = []
    p = Popen(quilt_machines, stdout=PIPE)
    lines = p.stdout.read().splitlines()
    for line in lines:
        m  = re.search(ip_pattern, line)
        if m:
            m = m.group(0)
            all_machines.append(m)
    return set(all_machines)
    
def initialize_machine(ssh_client):
        install_deps(ssh_client)

def install_deps(ssh_client):
    cmd_cpulimit = "sudo DEBIAN_FRONTEND=noninteractive apt-get install cpulimit"
    cmd_stress = "sudo DEBIAN_FRONTEND=noninteractive apt-get install stress"
    ssh_exec(ssh_client, cmd_cpulimit)
    ssh_exec(ssh_client, cmd_stress)

##TODO
def invalid_resource_parameter(resource, quantity):
    print ('Invalid resource paramater for {}, the quantity given is {}'.format(resource, quantity))
    return

'''Functions to get the performance utilizations of a container'''

container_to_cpu_utilization = {}
container_to_network_utilization = {}
container_to_disk_utilization = {}

#Kick off the Utilization Measurements Thread
def initialize_utilization_measurements(ssh_client):
    all_container_id = get_container_id(ssh_client, full_id=False, append_c=False)
    for container in all_container_id:
        container_to_cpu_utilization[container] = []
        container_to_network_utilization[container] = []
        container_to_disk_utilization[container] = []
            
    timer = start_measurement_timer(ssh_client)
    return timer

#Stop the measurement timer and then reset the global counters
def stop_utilization_measurements(measurement_thread):
    print ('STOPPING UTILIZATION')
    print (measurement_thread)
    measurement_thread.cancel()
    all_container_id = get_container_id(ssh_client, full_id=False, append_c=False)
    print (analyze_container_runtimes())

    for container in all_container_id:
        container_to_cpu_utilization[container] = []
        container_to_network_utilization[container] = []
        container_to_disk_utilization[container] = []

#Reset the timer values
def reset_analysis_values():
    container_to_cpu_utilization = {}
    container_to_network_utilization = {}
    container_to_disk_utilization = {}

#Analysis currently only checks to see who used a certain resource the most or least over the course of the entire experiment
def analyze_container_runtimes():
    cpu_max_difference = 0
    cpu_container_id = 0
    for container in container_to_cpu_utilization:
        if len(container_to_cpu_utilization[container]) > 0:
            difference = container_to_cpu_utilization[container][-1] - container_to_cpu_utilization[container][0]
            if difference > cpu_max_difference:
                cpu_max_difference = difference
                cpu_container_id = container

    disk_max_difference = 0
    disk_container_id = 0
    for container in container_to_disk_utilization:
        if len(container_to_disk_utilization[container]) > 0:
            difference = container_to_disk_utilization[container][-1] - container_to_disk_utilization[container][0]
            if difference > disk_max_difference:
                disk_max_difference = difference
                disk_container_id = container
                            
    network_max_difference = 0
    network_container_id = 0
    for container in container_to_network_utilization:
        if len(container_to_network_utilization[container]) > 0:
            difference = container_to_network_utilization[container][-1][0] - container_to_network_utilization[container][0][0]
            if difference > network_max_difference:
                network_max_difference = difference
                network_container_id = container

    return (cpu_max_difference, cpu_container_id, disk_max_difference, disk_container_id, network_max_difference, network_container_id)

#Starts a thread that consistently takes utilization measurements
def start_measurement_timer(ssh_client):
    timer_duration = 5.0
    timer = threading.Timer(timer_duration, start_measurement_timer, [ssh_client])
    timer.start()
    get_cpu_utilization(ssh_client)
    get_network_utilization(ssh_client)
    get_disk_utilization(ssh_client)
    return timer

#Assuming a static container set!
def get_utilization_diff(initial_utilization, final_utilization):
    utilization_diff = {}
    utilization_diff['cpu'] = final_utilization['cpu'] - initial_utilization['cpu']
    utilization_diff['network_outbound'] = final_utilization['network_outbound'] - initial_utilization['network_outbound']
    utilization_diff['network_inbound'] = final_utilization['network_inbound'] - initial_utilization['network_inbound']
    utilization_diff['disk'] = final_utilization['disk'] - initial_utilization['disk']
    return utilization_diff

#Converts CPU throttle time from nanoseconds to seconds
def get_cpu_throttle_time(ssh_client, throttle_time, increment):
    return throttle_time / (10**9)

def get_disk_throttle_time(ssh_client, result_in_bytes, increment):
    disk_throttle = float(result_in_bytes) / get_disk_capabilities(ssh_client, increment)
    return disk_throttle

def get_network_throttle_time(ssh_client, result_in_bytes, increment):
    all_container_interface_throttled = get_network_capabilities(ssh_client, increment)
    all_container_interface_baseline = get_network_capabilities(ssh_client, 0)
    network_throttle =  float(result_in_bytes) / all_container_interface_throttled.itervalues().next() - float(result_in_bytes) / all_container_interface_baseline.itervalues().next()
    return network_throttle

def get_current_memory(ssh_client):
    """Returns a tuple (memory size, unit) where unit is B, K, M, or G."""
    _, stdout, _ = ssh_client.exec_command("docker info | grep 'Total Memory: '")
    line = stdout.readline() # XXX: Check that warnings aren't included.
    if not line.startswith('Total Memory: '):
        return
    memory = line[len('Total Memory: '):]
    memory = memory.split()
    mem = float(memory[0])
    unit = memory[1]
    print ("CURR: {}".format((mem, unit)))
    return (mem, unit)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("public_vm_ip")
    parser.add_argument("--network_delay", type=float, default=-1.0, help="Network delay in milliseconds.")
    parser.add_argument("--rm_network_delay", action="store_true", help="Remove any artificial network delays.")
    parser.add_argument("--network_bandwidth", type=float, default=1.0, help="Network Bandwidth in kbps")
    parser.add_argument("--reset_network_bandwidth", action="store_true", help="Reset Network Bandwidth to the default value")
    parser.add_argument("--cpu_limit", type=int, default=-1, help="Limit CPU at CPU_LIMIT percent.")
    parser.add_argument("--rm_cpu_limit", action="store_true", help="Remove any cpu limits imposed with --cpu_limit.")
    args = parser.parse_args()
    ssh_client = quilt_ssh(args.public_vm_ip)
#       timer_handle = initialize_utilization_measurements(ssh_client)
    remove_all_network_manipulation(ssh_client)

    container_bandwidth = get_container_network_capacity(ssh_client)
    for container in container_bandwidth:
        container_bandwidth[container] = 100#0.2 * container_bandwidth[container]
    print container_bandwidth
    set_incoming_network_bandwidth(ssh_client)
    set_outgoing_network_bandwidth(ssh_client, container_bandwidth)

    if args.network_delay >= 0:
        set_network_delay(ssh_client, args.network_delay)
    if args.rm_network_delay or args.reset_network_bandwidth:
        remove_all_network_manipulation(ssh_client)
    if args.network_bandwidth >=0:
        set_network_bandwidth(ssh_client, args.network_bandwidth)
    if args.cpu_limit >= 0 and args.cpu_limit <= 100:
        install_deps(ssh_client)
        update_cpu(ssh_client, limit=args.cpu_limit)
    if args.rm_cpu_limit:
        reset_cpu(ssh_client)
    if args.mem_limit >= 0 and args.mem_limit <= 100:
        update_memory(ssh_client, containers, limit=args.mem_limit)

