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
import csv

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

def test_apt(traffic_gen_ip, num_traffic_pods, experiment_iterations):
    workload_config = {}
    workload_config['request_generator'] = [traffic_gen_ip]
    workload_config['workload_num'] = num_traffic_pods
    workload_config['type'] = 'apt-app'
    all_results = measure_runtime(workload_config, experiment_iterations)
    print all_results

def todo_robustness(traffic_gen_ip, num_traffic_pods,
                    experiment_iterations, concurrency_range,
                    performance_metric='latency_99'):
    
    workload_config = {}
    workload_config['request_generator'] = [traffic_gen_ip]
    workload_config['workload_num'] = num_traffic_pods
    workload_config['type'] = 'todo-app'

    concurrency_perf = {}
    concurrency_std = {}
    for concurrency in range(concurrency_range[0], concurrency_range[1], 10):
        performance = []
        for _ in range(experiment_iterations):
            perf = measure_TODO_response_time(workload_config,
                                              1,
                                              concurrency=concurrency)[performance_metric][0]
            performance.append(perf)
            
        concurrency_perf[concurrency] = np.mean(performance)
        concurrency_std[concurrency] = np.std(performance)

    return concurrency_perf, concurrency_std

def hotrod_robustness(traffic_gen_ip, num_traffic_pods,
                      experiment_iterations, concurrency_range,
                      performance_metric='latency_99'):
    workload_config = {}
    workload_config['request_generator'] = [traffic_gen_ip]
    workload_config['workload_num'] = num_traffic_pods
    workload_config['type'] = 'hotrod'

    concurrency_perf = {}
    concurrency_std = {}

    percentage_index = 0.5
    percentage_mapper = 0.25
    percentage_dispatch = 0.25
    for concurrency in range(concurrency_range[0], concurrency_range[1], 10):
        performance = []
        index_concurrency = percentage_index * concurrency
        dispatch_concurrency = percentage_dispatch * concurrency
        mapper_concurrency = percentage_mapper * concurrency
        
        for _ in range(experiment_iterations):
            perf = measure_hotrod(workload_config,
                           1,
                           index_concurrency=index_concurrency,
                           dispatch_concurrency=dispatch_concurrency,
                           mapper_concurrency=mapper_concurrency)

            performance.append(perf)

        concurrency_perf[concurrency] = np.mean(performance)
        concurrency_std[concurrency] = np.std(performance)

    return concurrency_perf, concurrency_std

def export_concurrency_results(concurrency_perf, concurrency_std,
                               output_csv='concurrency_results.csv'):
    with open(output_csv, 'w') as csvfile:
        fieldnames = ['CONCURRENCY', 'PERF', 'STD']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for concurrency in concurrency_perf.keys():
            result_dict= {}
            result_dict['CONCURRENCY'] = concurrency
            result_dict['PERF'] = concurrency_perf[concurrency]
            result_dict['STD'] = concurrency_std[concurrency]
            writer.writerow(result_dict)

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

def collect_percentiles(traffic_client, filename):
    # Read other percentiles (not something actionable to AutoTune)
    percentiles = [0, 25, 50, 75, 90, 99, 100]
    percentile_perf = {}
    for percentile in percentiles:
        percentile_command = 'awk -F, \'$1 == {}\' {}'.format(percentile, filename)
        _,perc_results,_ = traffic_client.exec_command(percentile_command)
        result_float = 0
        try:
            result_str = perc_results.read()
            print result_str
            result_float = float(result_str.split(',')[1])
            print result_float
        except:
            result_float = -1
        percentile_perf[percentile] = result_float

    return percentile_perf

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

def measure_TODO_response_time(workload_configuration, iterations, concurrency=200):
    num_traffic_generators = workload_configuration['workload_num']
    traffic_generator_ip = workload_configuration['request_generator'][0]

    all_requests = {}
    all_requests['latency_90'] = []
    all_requests['latency_99'] = []
    all_requests['rps'] = []
    all_requests['latency'] = []
    all_requests['latency_50'] = []

    CONCURRENCY = concurrency
    if concurrency <= 500:
        NUM_REQUESTS = 500
    else:
        NUM_REQUESTS = CONCURRENCY

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
        isCleared = False
        while isCleared is False:
            try:
                print 'attempting to clear'
                clear_attempt = requests.get(clear_entries_url, params={'w': num_traffic_generators}, timeout=10)
                print 'clear succeded!'
                isCleared = True
            except requests.exceptions.Timeout:
                print 'timeout happened'
                logging.info('Timeout occured while waiting for clearing to finish')
            except requests.exceptions.RequestException as e:
                print e

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
    num_traffic_generators = workload_config['workload_num']
    traffic_generator_ip = workload_config['request_generator'][0]

    POSTGRES_REQUESTS = 800
    NUM_REQUESTS = 800
    CONCURRENCY = 500

    num_postgresql_get = 1
    con_postgresql_get = 1
    num_postgresql_put = 20
    con_postgresql_put = 10
    num_mysql_get = 500
    con_mysql_get = 250
    num_mysql_put = 1
    con_mysql_put = 1
    num_welcome = 500
    con_welcome = 250
    num_elastic = 1
    con_elastic = 1
    
    all_requests = {}
    all_requests['latency_90'] = []
    all_requests['latency_99'] = []
    all_requests['rps'] = []
    all_requests['latency'] = []
    all_requests['latency_50'] = []

    latency_99_breakdown = {}

    successful_experiments = 0
    while successful_experiments < experiment_iterations:
        init_url = 'http://' + traffic_generator_ip + ':80/init'
        try:
            r = requests.get(init_url, params={'n': num_postgresql_get,
                                               'c': con_postgresql_get})
        except requests.exceptions.Timeout:
            logging.info('Timeout occured. Pausing for a bit before restarting')
            time.sleep(30)
            continue
        except requests.exceptions.RequestException as e:
            print e
            sys.exit(1)
        print 'Databases have been initiated'
        
        traffic_url = 'http://' + traffic_generator_ip + ':80/startab'
        try:
            r = requests.get(traffic_url, params={'w': num_traffic_generators,
                                                  'num_postgresql_get': num_postgresql_get,
                                                  'con_postgresql_get': con_postgresql_get,
                                                  'num_postgresql_put': num_postgresql_put,
                                                  'con_postgresql_put': con_postgresql_put,
                                                  'num_mysql_get': num_mysql_get,
                                                  'con_mysql_get': con_mysql_get,
                                                  'num_mysql_put': num_mysql_put,
                                                  'con_mysql_put': con_mysql_put,
                                                  'num_welcome': num_welcome,
                                                  'con_welcome': con_welcome,
                                                  'num_elastic': num_elastic,
                                                  'con_elastic': con_elastic})
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

            for endpoint in perf_dict.keys():
                if endpoint not in latency_99_breakdown:
                    latency_99_breakdown[endpoint] = []
                if 'latency_99' in perf_dict[endpoint]:
                    latency_99_breakdown[endpoint].append(perf_dict[endpoint]['latency_99'])

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

        delete_url = 'http://' + traffic_generator_ip + ':80/delete'
        try:
            r =	requests.get(delete_url)
	except requests.exceptions.Timeout:
            logging.info('Timeout occured. Pausing for a bit before restarting')
            time.sleep(30)
            continue
        except requests.exceptions.RequestException as e:
            print e
            sys.exit(1)
        print 'Databases have been initiated'

        logging.info(all_requests)
        print all_requests
        print 'Latency 99 breakdown is {}'.format(latency_99_breakdown)

    all_requests['rps'] = [np.median(all_requests['rps'])]
    all_requests['latency'] = [np.median(all_requests['latency'])]
    all_requests['latency_50'] = [np.median(all_requests['latency_50'])]
    all_requests['latency_90'] = [np.median(all_requests['latency_90'])]
    #all_requests['latency_99'] = [np.median(all_requests['latency_99'])]

    median = np.median(all_requests['latency_99'])
    std = np.std(all_requests['latency_99'])
    all_requests['latency_99'] = [i for i in all_requests['latency_99'] if (i >= (median - std) and i <= (median + std))]
    return all_requests

def measure_hotrod(workload_config, experiment_iterations,
                   index_concurrency=100, dispatch_concurrency=100, mapper_concurrency=100):
    num_traffic_generators = workload_config['workload_num']
    traffic_generator_ip = workload_config['request_generator'][0]

    all_requests = {}
    all_requests['latency_90'] = []
    all_requests['latency_99'] = []
    all_requests['rps'] = []
    all_requests['latency'] = []
    all_requests['latency_50'] = []

    if index_concurrency < 1000:
        NUM_INDEX_REQUESTS = 1000
    else:
        NUM_INDEX_REQUESTS = index_concurrency

    if dispatch_concurrency < 500:
        NUM_DISPATCH_REQUESTS = 500
    else:
        NUM_DISPATCH_REQUESTS = max(mapper_concurrency, dispatch_concurrency)

    successful_experiments = 0
    while successful_experiments < experiment_iterations:
        traffic_url = 'http://' + traffic_generator_ip + ':80/startab'
        try:
            r = requests.get(traffic_url, params={'w': num_traffic_generators,
                                                  'num_dispatch': dispatch_concurrency,
                                                  'num_index': index_concurrency,
                                                  'concurrency_mapper': mapper_concurrency,
                                                  'concurrency_index': index_concurrency,
                                                  'concurrency_dispatch': dispatch_concurrency})
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
    parser.add_argument("--concurrency_test")
    parser.add_argument("--concurrency_min")
    parser.add_argument("--concurrency_max")
    args = parser.parse_args()

    if args.concurrency_test == 'yes':
        concurrency_range = (int(args.concurrency_min), int(args.concurrency_max))
        if args.test_name == 'todo':
            concurrency_perf, concurrency_std = todo_robustness(args.traffic_ip, int(args.workload_num),
                                                                int(args.iterations), concurrency_range)
            export_concurrency_results(concurrency_perf, concurrency_std,
                                       output_csv='concurrency_results.csv')

        elif args.test_name == 'hotrod':
            concurrency_perf, concurrency_std = hotrod_robustness(args.traffic_ip, int(args.workload_num),
                                                                  int(args.iterations), concurrency_range)
            export_concurrency_results(concurrency_perf, concurrency_std,
                                       output_csv='concurrency_results.csv')

        
    else:
        if args.test_name == 'todo':
            test_todo(args.traffic_ip, int(args.workload_num), int(args.iterations))
            
        if args.test_name == 'hotrod':
            test_hotrod(args.traffic_ip, int(args.workload_num), int(args.iterations))

        if args.test_name == 'apt-app':
            print 'running apt app'
            test_apt(args.traffic_ip, int(args.workload_num), int(args.iterations))


            
    
