'''Samples the Resources of the host machine periodically'''
from weighting_conversions import *
from remote_execution import *
from container_information import *

def get_container_network_capacity(ssh_client, container_id):
    # Get the max capacity of the interface
    container_to_capacity = {}
    cmd = 'cat /sys/class/net/{}/speed'.format(container_id)
    _, stdout, _ = ssh_client.exec_command(cmd)

    # This is tricky! It will vary by machine. Ignoring the prior command because its a theoretical guarantee and usage will depend on whether it is happening on the cloud or not
    # http://stackoverflow.com/questions/18507405/ec2-instance-typess-exact-network-performance
    # Units here are Megabits/sec
    # TODO: Currently using m4.large
    max_capacity = 566
    container_to_capacity[container_id] = float(max_capacity)

    return container_to_capacity

def get_num_cores(ssh_client):
    num_cores_cmd = 'nproc --all'
    _, stdout, _ = ssh_client.exec_command(num_cores_cmd)
    return int(stdout.read())

# Get the raw amount of machine capabilities
# Returns (Clock speed in Hz, Disk Read speed, and Network Bandwidth of the interface
def get_cpu_capabilities(ssh_client):
    # Get clock speed
    clock_speed_cmd = 'lscpu | grep MHz | awk {{\'print $3\'}}'
    _, stdout, _ = ssh_client.exec_command(clock_speed_cmd)
    clock_speed_hertz = float(stdout.read()) * 1000000 #Converting from MHz to Hz
    return clock_speed_hertz

#Returns bandwidth in bytes/sec
def get_network_capabilities(ssh_client, container_id, stress_level):
    #hardcoding because we're pressed on time!
    container_to_capacity = get_container_network_capacity(ssh_client, container_id)
    container_to_network_bandwidth = weighting_to_bandwidth(ssh_client, stress_level, container_to_capacity)
    #Convert from MB/sec
    container_to_network_bandwidth.update((container, bandwidth*1000000) for container, bandwidth in container_to_network_bandwidth.items())
    return container_to_network_bandwidth

def get_disk_capabilities(ssh_client, stress_level):
    return weighting_to_disk_access_rate(stress_level)
