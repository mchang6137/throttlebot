'''
Converts various weightings between 0 and 100 to an actual amount to stress particular resource to
ALL UNITS IN BITS
All functions accept:
1.) Current allocation of resource
2.) Percentage to change resource. 
- A positive number means to increase the resource provisioning by a certain amount. 
- A negative numbers means to decrease the resource provisioning by a certain amount
Returns the new bandwdith
'''
from modify_resources import *
from remote_execution import *

# Converts a change in resource provisioning to raw change
# Example: 20% -> 24 Gbps
def convert_percent_to_raw(mr, current_mr_allocation, weight_change=0):
    if mr.resource == 'CPU-CORE':
        return weighting_to_cpu_cores(weight_change, current_mr_allocation)
    elif mr.resource == 'CPU-QUOTA':
        return weighting_to_cpu_quota(weight_change, current_mr_allocation)
    elif mr.resource == 'DISK':
        return  weighting_to_blkio(weight_change, current_mr_allocation)
    elif mr.resource == 'NET':
        return weighting_to_net_bandwidth(weight_change, current_mr_allocation)
    elif mr.resource == 'MEMORY':
        return weighting_to_memory(weight_change, current_mr_allocation, mr.instances)
    else:
        print 'INVALID resource'
        exit()

# Change the networking capacity
# Current Capacity in bits/p
def weighting_to_net_bandwidth(weight_change, current_alloc):
    new_bandwidth = current_alloc + ((weight_change / 100.0) * current_alloc)
    return int(new_bandwidth)

# Change the weighting on the blkio
# Conducted for the disk stressing
def weighting_to_blkio(weight_change, current_alloc):
    #+10 because blkio only accepts values between 10 and 1000
    #Lower weighting must have lower bound on the blkio weight allocation
    new_blkio = current_alloc + int((weight_change / 100.0) * current_alloc + 10)
    return int(new_blkio)

# Change the weighting of the CPU Quota
# TODO: Extend this to type of stressing to multiple cores
# Assumes a constant period
def weighting_to_cpu_quota(weight_change, current_alloc):
    # We divide by 100 because CPU quota allocation is given as percentage
    new_quota = current_alloc + current_alloc * weight_change/100.0
    return new_quota

# Alternative method of changing the CPU stresing
# Reduces the number of cores
# This is a special case, unlike the other types of stressing
def weighting_to_cpu_cores(weight_change, current_alloc):
    assert current_alloc > 0
    print 'hi', current_alloc
    new_cores = round(current_alloc + (weight_change / 100.0) * current_alloc)
    print 'hi2', new_cores
    if new_cores == current_alloc:
        if weight_change < 0:
            new_cores = current_alloc - 1
        else:
            new_cores = current_alloc + 1
            if new_cores <= 0:
                print 'Cannot shrink the number of cores anymore'
            return 1

    return new_cores

def weighting_to_memory(weight_change, current_alloc, instance):
    new_memory = current_alloc + int(current_alloc * weight_change/100.0)
    return new_memory

# This probably belongs in a different function
# Leaving here for convenience
def get_num_cores(ssh_client):
    num_cores_cmd = 'nproc --all'
    _, stdout, _ = ssh_client.exec_command(num_cores_cmd)
    return int(stdout.read())



