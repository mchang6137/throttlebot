'''

Resource provisioning is assigned in increments of 10. 
Assigns a new resource provision and then checks to see that the new resource provision is valid.

ALL UNITS IN BITS

All functions accept:
1.) Current allocation of resource
2.) Percentage to change resource. 
- A positive number means to increase the resource provisioning by a certain amount. 
- A negative numbers means to decrease the resource provisioning by a certain amount

Returns the newly calculated provisioning, and -1 if the proposed weight change creates an invalid 

'''
from modify_resources import *
from remote_execution import *

# Converts a change in resource provisioning to raw change
# Example: 20% -> 24 Gbps
def convert_percent_to_raw(mr, current_alloc, instance_type, weight_change=0):
    if mr.resource == 'CPU-CORE':
        return weighting_to_cpu_cores(weight_change, current_alloc, instance_type)
    elif mr.resource == 'CPU-QUOTA':
        return weighting_to_cpu_quota(weight_change, current_alloc, instance_type)
    elif mr.resource == 'DISK':
        return  weighting_to_blkio(weight_change, current_alloc, instance_type)
    elif mr.resource == 'NET':
        return weighting_to_net_bandwidth(weight_change, current_alloc, instance_type)
    elif mr.resource == 'MEMORY':
        return weighting_to_memory(weight_change, current_alloc, instance_type, mr.instances)
    else:
        print 'INVALID resource'
        exit()

# Change the networking capacity
# Current Capacity in bits/p
def weighting_to_net_bandwidth(weight_change, current_alloc, instance_type):
    total_allocation = get_instance_specs(instance_type)['NET']
    new_bandwidth = current_alloc + ((weight_change / 100.0) * total_allocation)
    if new_bandwidth > 0:
        return int(new_bandwidth)
    else:
        return -1

# Change the weighting on the blkio
# Conducted for the disk stressing
def weighting_to_blkio(weight_change, current_alloc, instance_type):
    #+10 because blkio only accepts values between 10 and 1000
        #Lower weighting must have lower bound on the blkio weight allocation
    total_allocation = 1000
    new_blkio = current_alloc + int((weight_change / 100.0) * total_allocation + 10)
    if new_blkio > 0:
        return int(new_blkio)
    else:
        return -1

# Change the weighting of the CPU Quota
# TODO: Extend this to type of stressing to multiple cores
# Assumes a constant period
def weighting_to_cpu_quota(weight_change, current_alloc, instance_type):
    total_alloc = 100 * get_instance_specs(instance_type)['CPU-CORE']
    # We divide by 100 because CPU quota allocation is given as percentage
    new_quota = current_alloc + (total_alloc * weight_change/100.0)
    if new_quota > 0:
        return int(new_quota)
    else:
        return -1

# Alternative method of changing the CPU stresing
# Reduces the number of cores
# This is a special case, unlike the other types of stressing
def weighting_to_cpu_cores(weight_change, current_alloc, instance_type):
    total_alloc = 100 * get_instance_specs(instance_type)['CPU-CORE']
    assert current_alloc > 0
    
    new_cores = round(current_alloc + (weight_change / 100.0) * total_alloc)
    if new_cores == current_alloc:
        if weight_change < 0:
            new_cores = current_alloc - 1
        else:
            new_cores = current_alloc + 1
    if num_cores <= 0:
        print 'Cannot shrink the number of cores anymore'
        return 1
    return new_cores

def weighting_to_memory(weight_change, current_alloc, instance_type, instance):
    total_alloc = 100 * get_instance_specs(instance_type)['MEMORY']
    new_memory = current_alloc + int(total_alloc * weight_change/100.0)
    min_memory = get_min_memory(instance[0])
    if new_memory > min_memory:
        return int(new_memory)
    else:
        return -1
    

# Units in MB
def get_min_memory(instance):
    return 200  # Hardcoded for now

