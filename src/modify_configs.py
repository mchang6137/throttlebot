'''
Function to help decide how to vary the amount of software configurations
This used to jointly scale resource and software configurations

Mostly hard-coded, but ultimately will require some architecting

'''

import redis_resource as resource_datastore

from instance_specs import *
from poll_cluster_state import *
from remote_execution import *

from mr import MR

spark_master_image = 'hantaowang/bcd-low-net-master'
spark_worker_image = 'hantaowang/bcd-low-net'

# Initializes the Configuration functions for a job
# Updates the MRs that have configurations in Redis
def init_conf_functions(workload_config, default_mr_config, redis_db):
    experiment_type = workload_config['type']
    if experiment_type == 'bcd':
        return init_bcd_config(workload_config, default_mr_config, redis_db)
    else:
        return workload_config

# Modifies the workload_config based on the services
# Return the workload_config by reference
def modify_mr_conf(mr, new_mr_allocation, workload_config, redis_db):
    if mr.resource not in redis_db.hgetall("tunable_mrs").keys():
        return workload_config
    if workload_config['type'] == 'bcd':
        return modify_bcd_config(mr, new_mr_allocation, workload_config)
    else:
        return workload_config

# Reset the based on the services
# Return the workload_config by reference
def reset_mr_conf(mr, workload_config, redis_db):
    if mr.resource not in redis_db.hgetall("tunable_mars").keys():
        return workload_config
    if workload_config['type'] == 'bcd':
        return reset_bcd_config(mr, workload_config, redis_db)
    else:
        return workload_config

# writes all config of vm_ip
def spark_rewrite_conf(vm_ip, config, new_value):

    read = "cat spark/conf/spark-defaults.conf"

    vm = vm_ip[0]
    client = get_client(vm[0])
    _, results, _ = client.exec_command(
        'docker exec {0} sh -c \"{1}\"'.format(vm[1], read))
    _ = results.channel.recv_exit_status()
    current_conf = results.read().split("\n")
    for i in range(len(current_conf)):
        line = current_conf[i].strip().split()
        if len(line) == 0:
            continue
        if line[0] == config:
            line[1] = str(new_value)
        current_conf[i] = line[0] + " " + line[1]
    write = "echo '{0}' > spark/conf/spark-defaults.conf".format("\n".join(current_conf).strip())
    close_client(client)
    correct = []
    for vi in vm_ip:
        client = get_client(vi[0])
        _, results, _ = client.exec_command(
            'docker exec {0} sh -c \"{1}\"'.format(vi[1], write))
        correct.append(results.channel.recv_exit_status() == 0)
        close_client(client)

    print "Set all {0} to {1}".format(config, new_value)

def init_bcd_config(workload_config, default_mr_config, redis_db):
    all_vm_ip = get_actual_vms()
    service_to_deployment = get_service_placements(all_vm_ip)

    # Specify the MRs that will require joint tuning with software configurations

    sparkms_core = MR(spark_master_image, 'CPU-CORE', [])
    sparkms_memory = MR(spark_master_image, 'MEMORY', [])
    sparkwk_core = MR(spark_worker_image, 'CPU-CORE', [])
    sparkwk_memory = MR(spark_worker_image, 'MEMORY', [])

    # Easy master container identification

    workload_config['request_generator'] = [service_to_deployment[spark_master_image][0][0]]
    workload_config['frontend'] = [service_to_deployment[spark_master_image][0][0]]
    workload_config['additional_args'] = {'container_id': service_to_deployment[spark_master_image][0][1]}

    # Save tunable MRs and its maximums.
    # Write the maximum provisining that the resources can be provisioned to
    # Machine size hard coded
    max_capacity = get_instance_specs("m4.2xlarge")
    for mr in default_mr_config:
        if mr == sparkms_core or mr == sparkwk_core:
            maximum_provision = max_capacity['CPU-CORE']
            redis_db.hset("tunable_mrs", mr.resource, maximum_provision)
        if mr == sparkms_memory or mr == sparkwk_memory:
            maximum_provision = max_capacity['MEMORY']
            redis_db.hset("tunable_mrs", mr.resource, maximum_provision)
    print "BCD Conf Settings Initialized"

    return workload_config

# bcd has two services that need to generate configurations
# 1.) bcd-spark-master (master service)
# 2.) bcd-spark (worker service)
def modify_bcd_config(mr, new_mr_allocation, workload_config):
    # HARDCODED TO THE SPEC
    DEFAULT_MEM = 1

    # need some way of finding the correct instances.
    all_vm_ip = get_actual_vms()
    service_to_deployment = get_service_placements(all_vm_ip)
    NUM_WORKERS = len(service_to_deployment[spark_worker_image])
    instances = service_to_deployment[spark_master_image] + service_to_deployment[spark_worker_image]

    if mr.service_name == spark_worker_image:
        if mr.resource == 'CPU-CORE':
            spark_rewrite_conf(instances, 'spark.executor.cores', int(new_mr_allocation))
            spark_rewrite_conf(instances, 'spark.cores.max', int(new_mr_allocation) * NUM_WORKERS)
        elif mr.resource == 'MEMORY':
            memg = new_mr_allocation / (1024 ** 3)
            memg = str(int(memg*DEFAULT_MEM)) + "g"
            spark_rewrite_conf(instances, 'spark.executor.memory', memg)

    elif mr.service_name == spark_master_image:
        if mr.resource == 'CPU-CORE':
            mr_allocation_int = int(new_mr_allocation)
            spark_rewrite_conf(instances, 'spark.driver.cores', mr_allocation_int)
        elif mr.resource == 'MEMORY':
            memg = new_mr_allocation / (1024 ** 3)
            memg = str(int(memg*DEFAULT_MEM)) + "g"
            spark_rewrite_conf(instances, 'spark.driver.memory', memg)

    return workload_config

def reset_bcd_config(mr, workload_config, redis_db):
    if mr.resource == 'CPU-CORE' or mr.resource == 'MEMORY':
        provision = redis_db.hget("tunable_mrs", mr.resource)
        return modify_mr_conf(mr, provision, workload_config)
    return workload_config