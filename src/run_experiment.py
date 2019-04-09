'''Body of Running Experiments'''
'''Can return multiple performance values, but MUST return as one entry in the dict to be latency' '''

from remote_execution import *
from modify_resources import *
from measure_performance_MEAN_py3 import *
from run_spark_streaming import *
import argparse
import numpy as np
import logging
import requests

def test_todo(traffic_gen_ip, num_traffic_pods, experiment_iterations):
    workload_config = {}
    workload_config['request_generator'] = [traffic_gen_ip]
    workload_config['workload_num'] = num_traffic_pods
    workload_config['type'] = 'todo-app'
    all_results = measure_runtime(workload_config, experiment_iterations)
    print all_results

def test_hotrod(traffic_gen_ip, num_traffic_pods, experiment_iterations):
    workload_config = {}
    workload_config['request_generator'] = [traffic_gen_ip]
    workload_config['workload_num'] = num_traffic_pods
    workload_config['type'] = 'hotrod'
    all_results = measure_runtime(workload_config, experiment_iterations)
    print all_results

# Measure the performance of the application in term of latency
# Note: Although unused in some experiments, container_id was included to maintain symmetry
def measure_runtime(workload_config, experiment_iterations, include_warmups=False):
    experiment_type = workload_config['type']
    if experiment_type == 'spark-ml-matrix':
        return measure_ml_matrix(workload_config, experiment_iterations)
    if experiment_type == 'REST':
        return measure_REST_response_time(workload_config, experiment_iterations)
    elif experiment_type == 'nginx-single':
        return measure_nginx_single_machine(workload_config, experiment_iterations)
    elif experiment_type == 'todo-app':
        return measure_TODO_response_time(workload_config, experiment_iterations)
    elif experiment_type == 'basic-get':
        return measure_GET_response_time(workload_config, experiment_iterations)
    elif experiment_type == 'spark-streaming':
        if include_warmups:
            measure_spark_streaming(workload_config, experiment_iterations)
        return measure_spark_streaming(workload_config, experiment_iterations)
    elif experiment_type == 'apt-app':
        return measure_apt_app(workload_config, experiment_iterations)
    elif experiment_type == 'elk':
        return measure_elk_stack(workload_config, experiment_iterations)
    elif experiment_type == 'bcd':
        return measure_bcd(workload_config, experiment_iterations)
    elif experiment_type == 'hotrod':
        return measure_hotrod(workload_config, experiment_iterations)
    else:
        logging.error('INVALID EXPERIMENT TYPE: {}'.format(experiment_type))
        exit()

#Resets all parameters of the experiment to default values
def reset_experiment(vm_ip, container_id):
    ssh_client = get_client(vm_ip)
    reset_all_stresses(ssh_client, container_id)
    try:
        clear_all_entries(vm_ip)
    except:
        logging.warning("Couldn't reset VM {}".format(vm_ip))
    close_client(ssh_client)

def execute_parse_results(ssh_client, cmd):
    _, results, _ = ssh_client.exec_command(cmd)
    try:
        results_str = results.read()
        results_float = float(results_str.strip('\n'))
    except Exception as e:
        # logging.info(results.read())
        results_float = -1
    return results_float

def execute_parallel_parse(parallel_client, cmd):
    output = parallel_client(cmd)
    host_to_output = {}
    try:
        for host, host_output in output.items():
            output_str = host_output.read()
            host_to_output[host] = float(output_str.strip('\n'))
    except Exception as e:
        host_to_ouput[host] = -1
    return host_to_output

# helper objects
class latencyResult():
    def __init__(self):
        self.latency = []
        self.success = []

    def __len__(self):
        return len(self.latency)

    def add(self, lat, suc, index):
        if index == len(self.latency):
            self.latency.append(lat)
            self.success.append(suc)
        else:
            self.latency[index] = lat
            self.success[index] = suc

    def failure(self):
        for i in range(0, len(self.success)):
            if self.success[i] == False:
                logging.warning("FAILURE: index {0} was False".format(i))
                return i
        return -1


def median(lst):
    n = len(lst)
    if n < 1:
        return None
    if n % 2 == 1:
        return sorted(lst)[n // 2]
    else:
        return sum(sorted(lst)[n // 2 - 1:n // 2 + 1]) / 2.0


def is_finished(latency, experiment_iterations):
    if len(latency) < experiment_iterations:
        logging.warning("LENGTH: latency is only {0} items but needs {1}".format(len(latency), experiment_iterations))
        return len(latency)
    elif latency.failure() != -1:
        return latency.failure()
    return -1


# Block Coordinate Descent
def measure_bcd(workload_configuration, experiment_iterations):
    traffic_generate_machine = workload_configuration['request_generator'][0]
    traffic_generate_container = workload_configuration['additional_args']['container_id']
    cmd = "./spark/bin/spark-submit --class edu.berkeley.cs.amplab.mlmatrix.BlockCoordinateDescent --num-executors 6 --driver-class-path /ml-matrix/target/scala-2.10/mlmatrix-assembly-0.1.jar /ml-matrix/target/scala-2.10/mlmatrix-assembly-0.1.1.jar spark://spark-ms.q:7077 500 100 100 3 1"
    parse_cmd = 'docker exec {0} sh -c \"cat ~/out.txt\" | awk \'{{print $3}}\''
    ssh_client = get_client(traffic_generate_machine)
    latency = latencyResult()

    stop = is_finished(latency, experiment_iterations)

    while stop != -1:
        logging.info('docker exec -ti {0} sh -c "{1}  > ~/out.txt"'.format(traffic_generate_container, cmd))
        _, results, error = ssh_client.exec_command(
            'docker exec {0} sh -c "{1} > ~/out.txt"'.format(traffic_generate_container, cmd))
        status = results.channel.recv_exit_status()
        logging.info("Test command was run successfully: {0}".format(status == 0))
        logging.info(parse_cmd.format(traffic_generate_container))
        r = execute_parse_results(ssh_client, parse_cmd.format(traffic_generate_container))
        logging.info("Results: {0}".format(r))
        latency.add(float(r), status == 0, stop)
        stop = is_finished(latency, experiment_iterations)
    x = [median(latency.latency)]

    close_client(ssh_client)

    logging.info("{}, {}".format(latency.latency, x[0]))
    return {'latency': x,
            'latency_50': x,
            'latency_99': x,
            'latency_90': x,
            'success': all(latency.success)}


# ELK
def measure_elk_stack(workload_configuration, experiment_iterations):
    traffic_generate_machine = workload_configuration['request_generator'][0]
    traffic_generate_container = workload_configuration['additional_args']['container_id']
    cmd_type = workload_configuration['additional_args']['command']
    if cmd_type == 'load':
        cmd = 'lumbersexual --load --rate 500 --timeout 30'
        parse_cmd = 'docker exec {0} sh -c \"cat ~/out.txt | grep \'Sent\'\" | awk \'{{print $2}}\''
    elif cmd_type == 'latency':
        cmd = 'lumbersexual --latency --uri http://elasticsearch.q:9200'
        parse_cmd = 'docker exec {0} sh -c \"cat ~/out.txt | grep \'Measured\'\" | awk \'{{print $3}}\''
    elif cmd_type == 'load_latency':
        cmd = 'lumbersexual --load --latency --uri http://elasticsearch.q:9200 --count 200000'
        parse_cmd = 'docker exec {0} sh -c \"cat ~/out.txt | grep \'Measured\'\" | awk \'{{print $3}}\''
    else:
        raise Exception("{0} is not a valid command type".format(cmd_type))
    ssh_client = get_client(traffic_generate_machine)
    latency = latencyResult()

    stop = is_finished(latency, experiment_iterations)

    while stop != -1:
        logging.info('docker exec -ti {0} sh -c "{1}  > ~/out.txt"'.format(traffic_generate_container, cmd))
        _, results, error = ssh_client.exec_command(
            'docker exec {0} sh -c "{1} > ~/out.txt"'.format(traffic_generate_container, cmd))
        status = results.channel.recv_exit_status()
        logging.info("Test command was run successfully: {0}".format(status == 0))
        logging.info(parse_cmd.format(traffic_generate_container))
        r = execute_parse_results(ssh_client, parse_cmd.format(traffic_generate_container))
        logging.info("Results: {0}".format(r))
        latency.add(float(r), status == 0, stop)
        stop = is_finished(latency, experiment_iterations)
    x = [median(latency.latency)]

    # Clear indices
    clear_cmd = 'curl -XDELETE http://elasticsearch.q:9200/*'
    docker_clear_cmd = 'docker exec -ti {} sh -c "{}"'.format(traffic_generate_container, clear_cmd)
    logging.info(docker_clear_cmd)
    _, results, error = ssh_client.exec_command(docker_clear_cmd)
    status = results.channel.recv_exit_status()
    logging.info('Clearing Index status: {}'.format(status == 0))
    
    close_client(ssh_client)

    logging.info(latency.latency, x[0])
    return {'latency': x,
            'latency_50': x,
            'latency_99': x,
            'latency_90': x,
            'success': all(latency.success)}


# Use the Apache Benchmarking suite to hit a single container
# experiment_args = [nginx_public_ip, pinging_machine]
def measure_nginx_single_machine(workload_configuration, experiment_iterations):
    nginx_public_ip = workload_configuration['frontend'][0]
    traffic_generate_machine = workload_configuration['request_generator'][0]

    ssh_client = get_client(traffic_generate_machine)

    NUM_REQUESTS = 5
    CONCURRENCY = 1
    ACCEPTABLE_MS = 60

    all_requests = {}
    all_requests['rps'] = []
    all_requests['latency'] = []
    all_requests['latency_50'] = []
    all_requests['latency_99'] = []
    all_requests['latency_90'] = []

    field_name = 'percent requests within {}'.format(ACCEPTABLE_MS)
    all_requests[field_name] = []

    for x in range(experiment_iterations):
        benchmark_cmd = 'ab -n {} -c {} -e results_file http://{}/ > output.txt'.format(NUM_REQUESTS, CONCURRENCY, nginx_public_ip)
        logging.info(benchmark_cmd)
        _, results, _ = ssh_client.exec_command(benchmark_cmd)
        results.read()

        rps_cmd = 'cat output.txt | grep \'Requests per second\' | awk {{\'print $4\'}}'
        latency_90_cmd = 'cat output.txt | grep \'90%\' | awk {\'print $2\'}'
        latency_50_cmd = 'cat output.txt | grep \'50%\' | awk {\'print $2\'}'
        latency_99_cmd = 'cat output.txt | grep \'99%\' | awk {\'print $2\'}'
        requests_within_time_cmd = 'awk -F"," \'$2 > {} {{print $1}}\' results_file | sed -n \'2p\''.format(ACCEPTABLE_MS)
        latency_overall_cmd = 'cat output.txt | grep \'Time per request\' | awk \'NR==1{{print $4}}\''

        all_requests['latency_90'].append(execute_parse_results(ssh_client, latency_90_cmd))
        all_requests['latency_99'].append(execute_parse_results(ssh_client, latency_99_cmd))
        all_requests['latency'].append(execute_parse_results(ssh_client, latency_overall_cmd) * NUM_REQUESTS)
        all_requests['latency_50'].append(execute_parse_results(ssh_client, latency_50_cmd))
        all_requests['rps'].append(execute_parse_results(ssh_client, rps_cmd))
        all_requests[field_name].append(execute_parse_results(ssh_client, requests_within_time_cmd))

    close_client(ssh_client)

    return all_requests

#Measure response time for Spark ML-Matrix
# Outdated
def measure_ml_matrix(workload_configuration, experiment_iterations):
    all_results = {}
    all_results['latency'] = []

    spark_master_public_ip = spark_args[0]
    spark_master_private_ip = spark_args[1]
    ssh_client = get_client(spark_master_public_ip)
    spark_class = '--class edu.berkeley.cs.amplab.mlmatrix.BlockCoordinateDescent '
    driver_class = '--driver-class-path ml-matrix/target/scala-2.10/mlmatrix-assembly-0.1.jar ml-matrix-master/target/scala-2.10/mlmatrix-assembly-0.1.1.jar '
    driver_memory = '--driver-memory 6G '
    executor_memory = '--executor-memory 6G '
    spark_master = 'spark://{}:7077 '.format(spark_master_private_ip)
    ml_matrix_args = '150 25 1024 3 1'

    master_container_name_cmd = 'docker ps | grep master | awk {{\'print $11\'}}'
    _, container_name, _ = ssh_client.exec_command(master_container_name_cmd)

    #FIX ME
    container_name = 'backstabbing_colden'
    spark_submit_cmd = 'spark/bin/spark-submit ' + driver_memory + executor_memory + spark_class + driver_class + spark_master + ml_matrix_args

    execute_spark_job = 'docker exec {} {}'.format(container_name, spark_submit_cmd)
    #execute_spark_job = 'docker exec {} {}'.format(container_name.read().strip('\n'), spark_submit_cmd)
    logging.info(execute_spark_job)

    #Run the experiment experiment_iteration number of times
    for x in range(experiment_iterations):
        _, runtime, _ = ssh_client.exec_command(execute_spark_job)
        logging.info('about to print the runtime read')
        result_time = runtime.read()
        logging.info(result_time)
        try:
            runtime = int(re.findall(r'\d+',  result_time)[0])
        except IndexError:
            logging.warning('Spark out of memory!')
            all_results['latency'].append(0)
            continue
        all_results['latency'].append(runtime)

    logging.info(all_results)

    return all_results

def measure_TODO_response_time(workload_configuration, iterations):
    num_traffic_generators = workload_configuration['workload_num']
    traffic_generator_ip = workload_configuration['request_generator'][0]

    all_requests = {}
    all_requests['latency_90'] = []
    all_requests['latency_99'] = []
    all_requests['rps'] = []
    all_requests['latency'] = []
    all_requests['latency_50'] = []

    NUM_REQUESTS = 500
    CONCURRENCY = 200

    for _ in range(iterations):
        traffic_url = 'http://' + traffic_generator_ip + ':80/startab'
        try:
            r = requests.get(traffic_url, params={'w': num_traffic_generators,
                                                  'n': NUM_REQUESTS,
                                                  'c': CONCURRENCY,
                                                  'port': 80,
                                                  'hostname': 'haproxy.q'})
        except requests.exceptions.Timeout:
            logging.info('Timeout occured. Pausing for a bit before restarting')
            time.sleep(30)
            continue
        except requests.exceptions.RequestException as e:
            print e
            sys.exit(1)
        print 'GET requests have been sent'
            
            
        collect_url = 'http://' + traffic_generator_ip + ':80/collectresults'
        try:
            collected = requests.get(collect_url, params={'w': num_traffic_generators}, timeout=2000)
            perf_dict = collected.json()
            print perf_dict
        except requests.exceptions.RequestException as e:
            print e
            sys.exit(1)
        if len(perf_dict.keys()) != 0:
            for k in perf_dict.keys():
                all_requests[k].append(perf_dict[k])
        else:
            print "Too long to wait for collection. Service is probable down"
            sys.exit(1)

        print 'Data has been collected: {}'.format(all_requests)

        clear_entries_url = 'http://' + traffic_generator_ip + ':80/clearentries'
        try:
            clear_attempt = requests.get(clear_entries_url, params={'w': num_traffic_generators})
        except requests.exceptions.Timeout:
            logging.info('Timeout occured while waiting for clearing to finish')
        except requests.exceptions.RequestException as e:
            print e
            sys.exit(1)

        print 'Data has been cleared'

        logging.info(all_requests)
        print all_requests

    return all_requests

#Measure response time for MEAN Application
def measure_REST_response_time(workload_configuration, iterations):
    REST_server_ip = workload_configuration['frontend'][0]
    ssh_server_ip = workload_configuration['request_generator'][0]
    #Each iteration actually represents 100 web requests
    all_requests = []
    for x in range(iterations):
        all_requests += POST_to_website(REST_server_ip, 100, num_threads=4, remote=True, ssh_ip=ssh_server_ip)
        clear_all_entries(REST_server_ip)
    numpy_all_requests = numpy.array(all_requests)
    mean = numpy.mean(numpy_all_requests)
    std = numpy.std(numpy_all_requests)
    #percentile99 = numpy.percentile(a, 99)
    return numpy.array(all_requests)

def measure_GET_response_time(workload_configuration, iterations):
    disknet_public_ip = workload_configuration['frontend'][0]
    traffic_generate_machine = workload_configuration['request_generator'][0]

    traffic_client = get_client(traffic_generate_machine)

    NUM_REQUESTS = 5
    CONCURRENCY = 1

    all_requests = {}
    all_requests['rps'] = []
    all_requests['latency'] = []
    all_requests['latency_50'] = []
    all_requests['latency_99'] = []
    all_requests['latency_90'] = []

    for x in range(iterations):
        # benchmark_cmd = 'ab -n {} -c {} -s 999999 -e results_file http://{}/ > output.txt'.format(NUM_REQUESTS,
        #                                                                                            CONCURRENCY,
        #                                                                                            disknet_public_ip)
        # logging.info(benchmark_cmd)
        # _, results, _ = traffic_client.exec_command(benchmark_cmd)
        # results.read()
        #
        # rps_cmd = 'cat output.txt | grep \'Requests per second\' | awk {{\'print $4\'}}'
        # latency_90_cmd = 'cat output.txt | grep \'90%\' | awk {\'print $2\'}'
        # latency_50_cmd = 'cat output.txt | grep \'50%\' | awk {\'print $2\'}'
        # latency_99_cmd = 'cat output.txt | grep \'99%\' | awk {\'print $2\'}'
        # latency_overall_cmd = 'cat output.txt | grep \'Time per request\' | awk \'NR==1{{print $4}}\''
        #
        # all_requests['latency_90'].append(execute_parse_results(traffic_client, latency_90_cmd))
        # all_requests['latency_99'].append(execute_parse_results(traffic_client, latency_99_cmd))
        # all_requests['latency'].append(execute_parse_results(traffic_client, latency_overall_cmd) * NUM_REQUESTS)
        # all_requests['latency_50'].append(execute_parse_results(traffic_client, latency_50_cmd))
        # all_requests['rps'].append(execute_parse_results(traffic_client, rps_cmd))

        benchmark_cmd = '(/usr/bin/time -f "%e" curl -so /dev/null {}) &> output.txt'.format(disknet_public_ip)
        logging.info(benchmark_cmd)
        _, results, _ = traffic_client.exec_command(benchmark_cmd)
        results.read()

        time_cmd = 'cat output.txt'
        time_elapsed = execute_parse_results(traffic_client, time_cmd)
        all_requests['latency_90'].append(time_elapsed)
        all_requests['latency_99'].append(time_elapsed)
        all_requests['latency'].append(time_elapsed)
        all_requests['latency_50'].append(time_elapsed)

    close_client(traffic_client)

    return all_requests

def measure_apt_app(workload_config, experiment_iterations):
    apt_app_public_ip = workload_config['frontend'][0]
    traffic_gen_ips = workload_config['request_generator']

    POSTGRES_REQUESTS = 800
    NUM_REQUESTS = 800
    CONCURRENCY = 500

    # traffic_clients = []
    # # Getting traffic machines
    # for ip in traffic_gen_ips:
    #     traffic_clients.append(get_client(ip))

    traffic_client = get_client(traffic_gen_ips[0])

    all_requests = {}
    all_requests['rps'] = []
    all_requests['latency'] = []
    all_requests['latency_50'] = []
    all_requests['latency_99'] = []
    all_requests['latency_90'] = []

    postgres_get = 'ab -q -n {} -c {} -s 9999 -e results_file http://{}:80/app/psql/users/ > output0.txt'.format(POSTGRES_REQUESTS, CONCURRENCY, apt_app_public_ip)
    postgres_post = 'ab -q -p post.json -T application/json -n {} -c {} -s 9999 -e results_file http://{}:80/app/psql/users/ > output1.txt'.format(POSTGRES_REQUESTS, CONCURRENCY, apt_app_public_ip)
    mysql_get = 'ab -q -n {} -c {} -s 9999 -e results_file http://{}:80/app/mysql/users/ > output2.txt'.format(NUM_REQUESTS, CONCURRENCY, apt_app_public_ip)
    mysql_post = 'ab -q -p post.json -T application/json -n {} -c {} -s 9999 -e results_file http://{}:80/app/mysql/users/ > output3.txt'.format(NUM_REQUESTS, CONCURRENCY, apt_app_public_ip)
    welcome = 'ab -q -n {} -c {} -s 9999 -e results_file http://{}:80/app/users/ > output4.txt'.format(NUM_REQUESTS, CONCURRENCY, apt_app_public_ip)
    elastic = 'ab -n 1 -s 9999 -e results_file http://{}:80/app/elastic/users/{} > output5.txt'.format(apt_app_public_ip, 3)

    benchmark_commands = [postgres_get, postgres_post, mysql_get, mysql_post, welcome, elastic]

    for x in range(experiment_iterations):

        # Initializing machine db
        logging.info('Initializing Machines')
        init_cmd = 'ab -p post.json -T application/json -n {} -c {} -s 9999 -e results_file http://{}:80/app/psql/users/'.format(
            NUM_REQUESTS, CONCURRENCY, apt_app_public_ip)
        logging.info(init_cmd)
        # _, results, _ = traffic_clients[0].exec_command(init_cmd)
        _, results, _ = traffic_client.exec_command(init_cmd)
        init_cmd = 'ab -p post.json -T application/json -n {} -c {} -s 9999 -e results_file http://{}:80/app/mysql/users/'.format(
            NUM_REQUESTS, CONCURRENCY, apt_app_public_ip)
        logging.info(init_cmd)
        # _, results, _ = traffic_clients[0].exec_command(init_cmd)
        _, results, _ = traffic_client.exec_command(init_cmd)

        logging.info("Sleeping for 2 seconds")
        sleep(2)

        # Checkpoint 1 (initialize machines)
        # logging.error('Reached Checkpoint 1! Check all traffic machines for post.json and db for entries')
        # exit()

        # Initiating requests
        for a in range(6):
            logging.info(benchmark_commands[a])
            #traffic_clients[a].exec_command(benchmark_commands[a])
            traffic_client.exec_command(benchmark_commands[a])
            sleep(0.2)

        # Checking for task completion
        finished = 0
        repetitions = 0
        # finished_benchmark_cmd = "cat output.txt | grep 'Requests per second' | awk {{'print $4'}}"
        logging.info('Please ignore the following new lines (if any)')
        sleep(5)
        while finished != 6:
            sleep(2)
            repetitions += 1
            finished = 0
            # Call again...
            if repetitions > 50:
                logging.info('Calling commands again due to unresponsiveness')
                for a in range(6):
                    logging.info(benchmark_commands[a])
                    # traffic_clients[a].exec_command(benchmark_commands[a])
                    traffic_client.exec_command(benchmark_commands[a])
                    sleep(0.2)
                repetitions = 0
                sleep(5)

            for b in range(6):
                finished_benchmark_cmd = "cat output{}.txt | grep 'Requests per second' | awk {{'print $4'}}".format(b)
                # blah = execute_parse_results(traffic_clients[b], finished_benchmark_cmd)
                complete = execute_parse_results(traffic_client, finished_benchmark_cmd)
                sleep(0.3)
                # logging.info("test {}".format(complete))
                if complete != -1:
                    finished += 1
                else:
                    break

        rps = 0
        latency = 0
        latency_50 = 0
        latency_90 = 0
        latency_99 = 0
        # rps_cmd = "cat output.txt | grep 'Requests per second' | awk {{'print $4'}}"
        # latency_cmd = "cat output.txt | grep 'Time per request' | awk 'NR==1{{print $4}}'"
        # latency_50_cmd = "cat output.txt | grep '50%' | awk {'print $2'}"
        # latency_90_cmd = "cat output.txt | grep '90%' | awk {'print $2'}"
        # latency_99_cmd = "cat output.txt | grep '99%' | awk {'print $2'}"

        # Grabbing data and removing files (TEMP VAR FOR DEBUGGING)
        for c in range(6):

            rps_cmd = "cat output{}.txt | grep 'Requests per second' | awk {{'print $4'}}".format(c)
            latency_cmd = "cat output{}.txt | grep 'Time per request' | awk 'NR==1{{print $4}}'".format(c)
            latency_50_cmd = "cat output{}.txt | grep '50%' | awk {{'print $2'}}".format(c)
            latency_90_cmd = "cat output{}.txt | grep '90%' | awk {{'print $2'}}".format(c)
            latency_99_cmd = "cat output{}.txt | grep '99%' | awk {{'print $2'}}".format(c)

            # Temporary Values
            # rpst = execute_parse_results(traffic_clients[c], rps_cmd)
            # latencyt = execute_parse_results(traffic_clients[c], latency_cmd)
            # latency_50t = execute_parse_results(traffic_clients[c], latency_50_cmd)
            # latency_90t = execute_parse_results(traffic_clients[c], latency_90_cmd)
            # latency_99t = execute_parse_results(traffic_clients[c], latency_99_cmd)
            #
            # rps += float(execute_parse_results(traffic_clients[c], rps_cmd))
            # latency += float(execute_parse_results(traffic_clients[c], latency_cmd))

            rpst = execute_parse_results(traffic_client, rps_cmd)
            sleep(0.3)
            latencyt = execute_parse_results(traffic_client, latency_cmd)
            sleep(0.3)
            latency_50t = execute_parse_results(traffic_client, latency_50_cmd)
            sleep(0.3)
            latency_90t = execute_parse_results(traffic_client, latency_90_cmd)
            sleep(0.3)
            latency_99t = execute_parse_results(traffic_client, latency_99_cmd)

            rps += float(execute_parse_results(traffic_client, rps_cmd))
            latency += float(execute_parse_results(traffic_client, latency_cmd))

            if latency_50t == -1:
                latency_50 += latencyt * 0.33
                latency_90 += latencyt * 0.33
                latency_99 += latencyt * 0.33
            else:
                latency_50 += latency_50t
                latency_90 += latency_90t
                latency_99 += latency_99t
            # traffic_clients[c].exec_command('rm output.txt')
            rm_out_cmd = 'rm output{}.txt'.format(c)
            traffic_client.exec_command(rm_out_cmd)
            sleep(0.3)
            logging.info('{},{},{},{},{}'.format(rpst, latencyt, latency_50t, latency_90t, latency_99t))
        logging.info('total:{},{},{},{},{}'.format(rps, latency, latency_50, latency_90, latency_99))

        # Removing entries
        curl1 = 'curl -X "DELETE" http://{}:80/app/mysql/users'.format(apt_app_public_ip)
        curl2 = 'curl -X "DELETE" http://{}:80/app/psql/users'.format(apt_app_public_ip)
        curl3 = 'curl http://{}:80/app/elastic/reset'.format(apt_app_public_ip)
        # fcurl1 = "for i in `seq {}`; do {}; done".format(NUM_REQUESTS, curl1)
        # fcurl2 = "for i in `seq {}`; do {}; done".format(NUM_REQUESTS, curl2)
        # traffic_clients[0].exec_command(curl1)
        # traffic_clients[0].exec_command(curl2)

        traffic_client.exec_command(curl1)
        sleep(0.3)
        traffic_client.exec_command(curl2)
        sleep(0.3)
        traffic_client.exec_command(curl3)
        logging.info('Sleeping for 15 seconds for proper deletion')
        sleep(15)
        traffic_client.exec_command(curl1)
        traffic_client.exec_command(curl2)

        logging.info('Sleeping for 5 more seconds for proper deletion')
        sleep(5)

        all_requests['rps'].append(rps)
        all_requests['latency'].append(latency)
        all_requests['latency_50'].append(latency_50)
        all_requests['latency_90'].append(latency_90)
        all_requests['latency_99'].append(latency_99)
        # TEMPORARY DELETE UP TO EXIT()
        # for client in traffic_clients:
        #     close_client(client)
        # close_client(traffic_client)
        # logging.info(all_requests)
        # logging.info('Checkpoint 2, Baseline and iteration done')
        # exit()

    # Remove outliers (all outside of 1 standard deviation)
    median = np.median(all_requests['rps'])
    std = np.std(all_requests['rps'])
    all_requests['rps'] = [i for i in all_requests['rps'] if (i >= (median - std) and i <= (median + std))]

    median = np.median( all_requests['latency'])
    std = np.std( all_requests['latency'])
    all_requests['latency'] = [i for i in all_requests['latency'] if (i >= (median - std) and i <= (median + std))]

    median = np.median(all_requests['latency_50'])
    std = np.std(all_requests['latency_50'])
    all_requests['latency_50'] = [i for i in all_requests['latency_50'] if (i >= (median - std) and i <= (median + std))]

    median = np.median(all_requests['latency_90'])
    std = np.std(all_requests['latency_90'])
    all_requests['latency_90'] = [i for i in all_requests['latency_90'] if (i >= (median - std) and i <= (median + std))]

    median = np.median(all_requests['latency_99'])
    std = np.std(all_requests['latency_99'])
    all_requests['latency_99'] = [i for i in all_requests['latency_99'] if (i >= (median - std) and i <= (median + std))]

    # Closing clients
    # for client in traffic_clients:
    #     close_client(client)
    close_client(traffic_client)

    return all_requests

def measure_hotrod(workload_config, experiment_iterations):
    num_traffic_generators = workload_config['workload_num']
    traffic_generator_ip = workload_config['request_generator'][0]

    all_requests = {}
    all_requests['latency_90'] = []
    all_requests['latency_99'] = []
    all_requests['rps'] = []
    all_requests['latency'] = []
    all_requests['latency_50'] = []

    NUM_INDEX_REQUESTS = 1000
    NUM_DISPATCH_REQUESTS = 500
    CONCURRENCY = 100

    successful_experiments = 0
    while successful_experiments < experiment_iterations:
        traffic_url = 'http://' + traffic_generator_ip + ':80/startab'
        try:
            r = requests.get(traffic_url, params={'w': num_traffic_generators,
                                                  'num_dispatch': NUM_DISPATCH_REQUESTS,
                                                  'num_index': NUM_INDEX_REQUESTS,
                                                  'c': CONCURRENCY})
        except requests.exceptions.Timeout:
            logging.info('Timeout occured. Pausing for a bit before restarting')
            time.sleep(30)
            continue
        except requests.exceptions.RequestException as e:
            print e
            sys.exit(1)
        print 'GET requests have been sent'

        data_collected = False
        collect_url = 'http://' + traffic_generator_ip + ':80/collectresults'
        try:
            collected = requests.get(collect_url, params={'w': num_traffic_generators})
            perf_dict = collected.json()
            print perf_dict
            data_collected = True
        except:
            print 'Failure Detected. Sleep 200 seconds'
            time.sleep(100)
            
        # Linear combination of all entries (no weighting)
        if data_collected:
            perf_linear = {}
            for endpoint in perf_dict.keys():
                for perf_field in perf_dict[endpoint]:
                    if perf_field not in perf_linear:
                        perf_linear[perf_field] = perf_dict[endpoint][perf_field]
                    else:
                        perf_linear[perf_field] += perf_dict[endpoint][perf_field]
            
            if len(perf_linear.keys()) != 0:
                for k in perf_linear.keys():
                    all_requests[k].append(perf_linear[k])
            else:
                print "Too long to wait for collection. Service is probable down"
                sys.exit(1)

            print 'Data has been collected: {}'.format(all_requests)
            successful_experiments += 1
            print 'Successful experiments is {}'.format(successful_experiments)
        else:
            print 'Data has not been collected. Clearing data and restarting experiment.'

        clear_entries_url = 'http://' + traffic_generator_ip + ':80/clearentries'
        try:
            clear_attempt = requests.get(clear_entries_url, params={'w': num_traffic_generators})
        except requests.exceptions.Timeout:
            logging.info('Timeout occured while waiting for clearing to finish')
        except requests.exceptions.RequestException as e:
            print e
            sys.exit(1)

        print 'Data has been cleared'

        logging.info(all_requests)
        print all_requests

    all_requests['rps'] = [np.median(all_requests['rps'])]
    all_requests['latency'] = [np.median(all_requests['latency'])]
    all_requests['latency_50'] = [np.median(all_requests['latency_50'])]
    all_requests['latency_90'] = [np.median(all_requests['latency_90'])]
    all_requests['latency_99'] = [np.median(all_requests['latency_99'])]
    return all_requests

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--test_name")
    parser.add_argument("--traffic_ip")
    parser.add_argument("--workload_num")
    parser.add_argument("--iterations")
    args = parser.parse_args()

    if args.test_name == 'todo':
        test_todo(args.traffic_ip, int(args.workload_num), int(args.iterations))

    if args.test_name == 'hotrod':
        test_hotrod(args.traffic_ip, int(args.workload_num), int(args.iterations))
    
