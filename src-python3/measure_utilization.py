''' Toolbox for measuring real-time utilizations of disk, cpu, and network'''
import paramiko
from remote_execution import *
from container_information import *

# Gets all resource utilizations for JUST the container in the machine specified in ssh_client
# Perhaps we need to collect the information for the other machines also?
# Keep track of the total amount of utilization for a resource at a certain point in time
def get_all_throttled_utilizations(ssh_client, container_id):
    utilization_dict = {}
    utilization_dict['cpu'] = get_throttled_cpu_amount(ssh_client, container_id)
    utilization_dict['disk'] = get_disk_eater_utilization(ssh_client, container_id)
    utilization_dict['network_outbound'], utilization_dict['network_inbound'] = get_network_utilization(ssh_client, container_id)
    return utilization_dict


#Get the throttled amount in nanoseconds
def get_throttled_cpu_amount(ssh_client, container_id):

    throttle_file_cmd = 'cat /sys/fs/cgroup/cpu/docker/{}/cpu.stat | grep throttled_time | awk {{\'print $2\'}}'.format(container_id)
    _, throttle_time, _ = ssh_client.exec_command(throttle_file_cmd)
    throttle_time_string = throttle_time.read()
    total_throttle_time = int(throttle_time_string.strip('\n'))

    return total_throttle_time

#Gets the inbound and outbound number of bytes sent from the container interface
def get_network_utilization(ssh_client, container_id):
    network_file = '/proc/net/dev'
    # Does this work? Exception will be caught in the event of no interface?
    _,stdout,_ = ssh_client.exec_command('cat {} | grep {} | awk {{\'print $2, $10\'}}'.format(network_file, container_id))
    try:
            network_list = stdout.read().strip('\n').split(' ')
    except:
        pass
    if len(network_list) == 2:
        send_bytes = int(network_list[0])
        rcv_bytes = int(network_list[1])
        outbound_container_utilization += send_bytes
        inbound_container_utilization += rcv_bytes

    return outbound_container_utilization, inbound_container_utilization

# Legacy (?)
# Checks the disk utilization of the disk_eater container that uses disk
def get_disk_eater_utilization(ssh_client, container_id):
    disk_eater_id_cmd = 'docker inspect --format=\"{{.Id}}\" disk_eater'
    _, disk_eater_id, _ = ssh_client.exec_command(disk_eater_id_cmd)
    disk_eater_id_temp = disk_eater_id.read()
    disk_eater_id_str = disk_eater_id_temp.strip('\n')

    blkio_file_cmd = 'cat /sys/fs/cgroup/blkio/docker/{}/blkio.throttle.io_service_bytes | grep Total | tail -n 1'.format(disk_eater_id_str)
    _,disk_reads,_ = ssh_client.exec_command(blkio_file_cmd)
    blkio =  int(disk_reads.read().split(' ')[1].strip('\n'))
    return blkio

# Assuming a static container set!
def get_utilization_diff(initial_utilization, final_utilization):
    utilization_diff = {}
    utilization_diff['cpu'] = final_utilization['cpu'] - initial_utilization['cpu']
    utilization_diff['network_outbound'] = final_utilization['network_outbound'] - initial_utilization['network_outbound']
    utilization_diff['network_inbound'] = final_utilization['network_inbound'] - initial_utilization['network_inbound']
    utilization_diff['disk'] = final_utilization['disk'] - initial_utilization['disk']
    return utilization_diff
