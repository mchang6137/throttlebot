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

import redis_resource as resource_datastore

# Converts a change in resource provisioning to raw change
# If current_mr_allocation is None, just stress relative to the current provision
# Example: 20% -> 24 Gbps
def convert_percent_to_raw(mr, redis_db, weight_change=0, current_mr_allocation=None):
    # Recover the current allocation for a MR
    if current_mr_allocation is None:
        current_mr_allocation = resource_datastore.read_mr_alloc(redis_db, mr)
    
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
    assert new_bandwidth > 0
    return int(new_bandwidth)

# Change the weighting on the blkio
# Conducted for the disk stressing
def weighting_to_blkio(weight_change, current_alloc):
    #+10 because blkio only accepts values between 10 and 1000
    #Lower weighting must have lower bound on the blkio weight allocation
    new_blkio = current_alloc + int((weight_change / 100.0) * current_alloc + 10)
    assert new_blkio > 0
    return int(new_blkio)

# Change the weighting of the CPU Quota
# TODO: Extend this to type of stressing to multiple cores
# Assumes a constant period
def weighting_to_cpu_quota(weight_change, current_alloc):
    # We divide by 100 because CPU quota allocation is given as percentage
    new_quota = current_alloc + current_alloc * weight_change/100.0
    assert new_quota > 0
    return new_quota

# Alternative method of changing the CPU stresing
# If stress level is negative, reduce one core no matter what.
# If stress level is positive, add one core no matter what
# Returns a CPU-QUOTA
def weighting_to_cpu_cores(weight_change, core_alloc):
    # If the core alloc is already at minimum, return -1
    if core_alloc == 1:
        return -1
    
    if weight_change < 0:
        return core_alloc - 1
    if weight_change > 0:
        return core_alloc + 1
    elif weight_change == 0:
        return core_alloc
    
    return new_core_alloc

def weighting_to_memory(weight_change, current_alloc, instance):
    new_memory = current_alloc + int(current_alloc * weight_change/100.0)
    return new_memory





