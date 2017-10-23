'''
Function to help decide how to vary the amount of software configurations
This used to jointly scale resource and software configurations

Mostly hard-coded, but ultimately will require some architecting

'''

import redis_resource as resource_datastore

from instance_specs import *
from poll_cluster_state import *
from mr import MR

# Initializes the Configuration functions for a job
# Updates the MRs that have configurations in Redis
def init_conf_functions(workload_config, redis_db, default_mr_config):
    experiment_type = workload_config['type']
    if experiment_type == 'bcd':
        return init_bcd_config(workload_config, redis_db, default_mr_config)
    else:
        return workload_config

# Modifies the workload_config based on the services
# Return the workload_config by reference
def modify_mr_conf(mr, new_mr_allocation, workload_config, redis_db):
    if mr not in resource_datastore.read_tunable_mr(redis_db):
        return workload_config
    if workload_config['type'] == 'bcd':
        return modify_bcd_config(workload_config, mr, new_mr_allocation)
    else:
        return workload_config

# writes all config of vm_ip
def spark_rewrite_conf(vm_ip, search, replace):
    correct = []
    for vi in vm_ip:
        client = get_client(vi[0])
        cmd = 'sed -i \'s;{0};{1};\' ./spark/conf/spark-defaults.conf'.format(search, replace)
        _, results, _ = client.exec_command(
            'docker exec {0} sh -c \"{1}\"'.format(vi[1], cmd))
        correct.append(results.channel.recv_exit_status() == 0)
        _ = results.channel.recv_exit_status()
    print "Set all {0} -> {1}: {2}".format(search, replace.split()[1], all(correct))

def init_bcd_config(workload_config, redis_db, default_mr_config):
    all_vm_ip = get_actual_vms()
    service_to_deployment = get_service_placements(all_vm_ip)

    spark_master_image = 'hantaowang/bcd-spark-master'
    spark_worker_image = 'hantaowang/bcd-spark'

    workload_config['request_generator'] = [service_to_deployment[spark_master_image][0][0]]
    workload_config['frontend'] = [service_to_deployment[spark_master_image][0][0]]
    workload_config['additional_args'] = {'container_id': service_to_deployment[spark_master_image][0][1]}

    # Creating Dummy MRs here since the instances are not considered in the hashing
    sparkms_core = MR(spark_master_image, 'CPU-CORE', [])
    sparkms_memory = MR(spark_master_image, 'MEMORY', [])
    sparkwk_core = MR(spark_worker_image, 'CPU-CORE', [])
    sparkwk_memory = MR(spark_worker_image, 'MEMORY', [])

    workload_config['resource_fct'][sparkms_core]['spark.driver.cores'] = '8'
    workload_config['resource_fct'][sparkwk_core]['spark.executor.cores'] = '8'
    workload_config['resource_fct'][sparkwk_core]['spark.cores.max'] = '48'
    
    workload_config['resource_fct'][sparkwk_memory]['spark.executor.memory'] = '25g'
    workload_config['resource_fct'][sparkms_memory]['spark.driver.memory'] = '25g'

    max_capacity = get_instance_specs(machine_type)[mr.resource]
    
    # Write the configuration maximum capacities to Redis
    for mr in default_mr_config:
        if mr == sparkms_core or mr == sparkwk_core:
            for instance in mr.instances:
                vm_ip,container_id = instance
                resource_datastore.write_config_capacity(redis_db, vm_ip, mr, max_capacity['CPU-CORE'])
        if mr == sparkms_memory or mr == sparkwk_memory:
            for instance in mr.instances:
                vm_ip,container_id = instance
                resource_datastore.write_config_capacity(redis_db, vm_ip, max_capacity['MEMORY'])

    # Add MRs to the tunable MR list
    resource_datastore.write_tunable_mr(redis_db, mr)
    return workload_config

# bcd has two services that need to generate configurations
# 1.) bcd-spark-master (master service)
# 2.) bcd-spark (worker service)
def modify_bcd_config(mr, new_mr_allocation, workload_config):
    # HARDCODED TO THE SPEC
    NUM_WORKERS = 6
    DEFAULT_MEM = 0.8

    spark_master_image = 'hantaowang/bcd-spark-master'
    spark_worker_image = 'hantaowang/bcd-spark'
    
    previous_allocation_dict = wc['resource_fct'][mr]

    #### need some way of finding the correct instances.
    all_vm_ip = get_actual_vms()
    service_to_deployment = get_service_placements(all_vm_ip)
    instances = service_to_deployment[spark_master_image] + spark_to_deployment[spark_worker_image]
    
    if mr.service_name == 'hantaowang/bcd-spark':
        if mr.resource == 'CPU-CORE':
            spark_rewrite_conf(instances, 'spark.executor.cores {0}'.format(previous_allocation_dict['spark.executor.cores']),
                               'spark.executor.cores {0}'.format(int(new_mr_allocation)))
            spark_rewrite_conf(instances, 'spark.cores.max {0}'.format(previous_allocation_dict['spark.cores.max']),
                               'spark.cores.max {0}'.format(int(new_mr_allocation * NUM_WORKERS)))
            wc['resource_fct'][mr]['spark.executor.cores'] = str(new_mr_allocation)
            wc['resource_fct'][mr]['spark.cores.max'] = str(int(new_mr_allocation * NUM_WORKERS))
        elif mr.resource == 'MEMORY':
            memg = new_mr_allocation / (1024 ** 3)
            memg = str(int(memg*DEFAULT_MEM)) + "g"
            spark_rewrite_conf(instances, 'spark.executor.memory {0}'.format(previous_allocation_dict['spark.executor.memory']),
                               'spark.executor.memory {0}'.format(memg))
            wc['resource_fct'][mr]['spark.executor.memory'] = memg
            
    elif mr.service_name == 'hantaowang/bcd-spark-master':
        if mr.resource == 'CPU-CORE':
            mr_allocation_int = int(new_mr_allocation)
            spark_rewrite_conf(instances, 'spark.driver.cores {0}'.format(previous_allocation_dict['spark.driver.cores']),
                            'spark.driver.cores {0}'.format(mr_allocation_int))
            wc['resource_fct'][mr]['spark.driver.cores'] = str(mr_allocation_int)
        elif mr.resource == 'MEMORY':
            memg = new_mr_allocation / (1024 ** 3)
            memg = str(int(memg*DEFAULT_MEM)) + "g"
            spark_rewrite_conf(instances, 'spark.driver.memory {0}'.format(previous_alloation_dict['spark.driver.memory']),
                               'spark.driver.memory {0}'.format(memg))
            wc['resource_fct'][mr]['spark.driver.memory'] = memg

    return workload_config


    
