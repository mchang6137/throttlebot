import redis.client
import redis_client as tbot_datastore

from mr import MR

'''
Get Information relating to MRs
'''

# Returns a list of MR as MR objects
def get_all_mrs(redis_db):
    mr_name = 'mr_alloc'
    all_mrs = redis_db.hgetall(mr_name)
    mr_list = list(all_mrs.keys())
    mr_object_list = []
    for mr in mr_list:
        service_name,resource = mr.split(',')
        deployments = tbot_datastore.read_service_locations(redis_db, service_name)
        mr_object_list.append(MR(service_name, resource, deployments))
    return mr_object_list

'''
This is specifically for the storing and accessing of the redis data 
relating to the current resource allocation of a MR
'''

def generate_mr_key(mr_service, mr_resource):
    return '{},{}'.format(mr_service, mr_resource)

def write_mr_alloc(redis_db, mr, new_allocation):
    mr_name = 'mr_alloc'
    key = generate_mr_key(mr.service_name, mr.resource)
    redis_db.hset(mr_name, key, new_allocation)

def read_mr_alloc(redis_db, mr):
    mr_name = 'mr_alloc'
    key = generate_mr_key(mr.service_name, mr.resource)
    return float(redis_db.hget(mr_name, key))

# Returns a list of MR objects with their current allocations
def read_all_mr_alloc(redis_db):
    mr_name = 'mr_alloc'
    mr_to_score = redis_db.hgetall(mr_name)
    for mr in mr_to_score:
        mr_to_score[mr] = float(mr_to_score[mr])

    mr_allocation_list = {}
    for mr in mr_to_score:
        service_name,resource = mr.split(',')
        deployments = tbot_datastore.read_service_locations(redis_db, service_name)
        mr_object = MR(service_name, resource, deployments)
        mr_allocation_list[mr_object] = mr_to_score[mr]
        
    return mr_allocation_list
    

'''
Machine Consumption index maps a particular VM (identified by IP address) to 
it's specific resource allocation: both in terms of the total maximal 
capacity to the full amount
'''

# machine_cap is a dict that stores the machine's maximum capacity
# machine_util is a tuple that stores the machine's current usage level
def write_machine_consumption(redis_db, machine_ip, machine_util):
    name = '{}machine_consumption'.format(machine_ip)
    for key in machine_util:
        redis_db.hset(name, key, machine_util[key])

def read_machine_consumption(redis_db, machine_ip):
    machine_util = {}
    name = '{}machine_consumption'.format(machine_ip)
    machine_consumption = redis_db.hgetall(name)

    for resource in machine_consumption:
        machine_consumption[resource] = float(machine_consumption[resource])
    return machine_consumption

def write_machine_capacity(redis_db, machine_ip, machine_cap):
    name = '{}machine_capacity'.format(machine_ip)
    for key in machine_cap:
        redis_db.hset(name, key, machine_cap[key])

def read_machine_capacity(redis_db, machine_ip):
    machine_cap = {}
    name = '{}machine_capacity'.format(machine_ip)
    
    machine_capacity = redis_db.hgetall(name)
    for resource in machine_capacity:
        machine_capacity[resource] = float(machine_capacity[resource])
    return machine_capacity


    

