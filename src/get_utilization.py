import paramiko

from container_information import *
from subprocess import Popen, PIPE
from remote_execution import *

import logging

# Gets the current memory utilization in bytes
def get_current_memory_utilization(ssh_client, container_id):
    get_memory_cmd = 'cat /sys/fs/cgroup/memory/docker/{}*/memory.usage_in_bytes'.format(container_id)
    _,memory_utilization_obj,stderr = ssh_exec(ssh_client, get_memory_cmd, modifies_container=True, return_error=True)

    memory_utilization_string = memory_utilization_obj.read()
    memory_utilization_float = float("".join(memory_utilization_string.split()))

    logging.info("Recovering the memory utilization")

    return memory_utilization_float
