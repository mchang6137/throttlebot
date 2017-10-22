'''
Function to help decide how to vary the amount of software configurations
This used to jointly scale resource and software configurations

Mostly hard-coded, but ultimately will require some architecting

'''

# Modifies the workload_config based on the services
# Return the workload_config by reference
def generate_conf_functions(mr, new_mr_allocation, workload_config):
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

# bcd has two services that need to generate configurations
# 1.) bcd-spark-master (master service)
# 2.) bcd-spark (worker service)
def modify_bcd_config(mr, new_mr_allocation, workload_config):
    # HARDCODED TO THE SPEC
    NUM_WORKERS = 6
    DEFAULT_MEM = 0.8

    previous_allocation_dict = wc['resource_fct'][mr]
    all_vm_ip = get_actual_vms()
    if mr.service_name == 'hantaowang/bcd-spark':
        if mr.resource == 'CPU-CORE':
            spark_rewrite_conf(vm_ip_all, 'spark.executor.cores {0}'.format(previous_allocation_dict['spark.executor.cores']),
                               'spark.executor.cores {0}'.format(int(new_mr_allocation)))
            spark_rewrite_conf(vm_ip_all, 'spark.cores.max {0}'.format(previous_allocation_dict['spark.cores.max']),
                               'spark.cores.max {0}'.format(int(new_mr_allocation * NUM_WORKERS)))
            wc['resource_fct'][mr]['spark.executor.cores'] = str(new_mr_allocation)
            wc['resource_fct'][mr]['spark.cores.max'] = str(int(new_mr_allocation * NUM_WORKERS))
        elif mr.resource == 'MEMORY':
            memg = new_mr_allocation / (1024 ** 3)
            memg = str(int(memg*DEFAULT_MEM)) + "g"
            spark_rewrite_conf(vm_ip_all, 'spark.executor.memory {0}'.format(previous_allocation_dict['spark.executor.memory']),
                               'spark.executor.memory {0}'.format(memg))
            wc['resource_fct'][mr]['spark.executor.memory'] = memg
            
    elif mr.service_name == 'hantaowang/bcd-spark-master':
        if mr.resource == 'CPU-CORE':
            mr_allocation_int = int(new_mr_allocation)
            spark_rewrite_conf(vm_ip_all, 'spark.driver.cores {0}'.format(previous_allocation_dict['spark.driver.cores']),
                            'spark.driver.cores {0}'.format(mr_allocation_int))
            wc['resource_fct'][mr]['spark.driver.cores'] = str(mr_allocation_int)
        elif mr.resource == 'MEMORY':
            memg = new_mr_allocation / (1024 ** 3)
            memg = str(int(memg*DEFAULT_MEM)) + "g"
            spark_rewrite_conf(vm_ip_all, 'spark.driver.memory {0}'.format(previous_alloation_dict['spark.driver.memory']),
                               'spark.driver.memory {0}'.format(memg))
            wc['resource_fct'][mr]['spark.driver.memory'] = memg

    return workload_config


    
