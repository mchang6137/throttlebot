import paramiko

from container_information import *
from subprocess import Popen, PIPE
from remote_execution import *

# Gets the current memory utilization in bytes
def get_current_memory_utilization(ssh_client, container_id):
    get_memory_cmd = 'cat /sys/fs/cgroup/memory/docker/{}*/memory.usage_in_bytes'.format(container_id)
    _,memory_utilization,_ = ssh_client.exec_command(get_memory_cmd)
    print "Recovering the memory utilization"
    return float(memory_utilization.read())
    
    
