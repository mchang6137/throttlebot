'''Body of Running Experiments'''
'''Can return multiple performance values, but MUST return as one entry in the dict to be latency' '''

from remote_execution import *
from modify_resources import *
from measure_performance_MEAN_py3 import *

#Measure the performance of the application in term of latency
def measure_runtime(experiment_args, experiment_iterations, experiment_type):
    if experiment_type == 'spark-ml-matrix':
        return measure_ml_matrix(experiment_args, experiment_iterations)
    if experiment_type == 'REST':
        return measure_REST_response_time(experiment_args, experiment_iterations)
    elif experiment_type == 'nginx-single':
        return measure_nginx_single_machine(experiment_args, experiment_iterations)
    elif experiment_type == 'todo-app':
        return measure_TODO_response_time(experiment_args, experiment_iterations)
    else:
        print ('INVALID EXPERIMENT TYPE')
        exit()

#Resets all parameters of the experiment to default values
def reset_experiment(vm_ip):
    ssh_client = quilt_ssh(vm_ip)
    reset_all_stresses(ssh_client)
    try:
        clear_all_entries(vm_ip)
    except:
        print ("Couldn't reset VM {}".format(vm_ip))

#Use the Apache Benchmarking suite to hit a single machine
#experiment_args = [nginx_public_ip, pinging_machine]
def measure_nginx_single_machine(experiment_args, experiment_iterations):
    nginx_public_ip = experiment_args[0]
    traffic_generate_machine = experiment_args[1]
    
    ssh_client = quilt_ssh(traffic_generate_machine)
    nginx_ssh_client = quilt_ssh(nginx_public_ip)

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
    
    utilization_diffs = []

    for x in range(experiment_iterations):
        initial_utilizations = get_all_throttled_utilizations(nginx_ssh_client)
        benchmark_cmd = 'ab -n {} -c {} -e results_file http://{}/ > output.txt'.format(NUM_REQUESTS, CONCURRENCY, nginx_public_ip)
        print benchmark_cmd
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

        final_utilizations = get_all_throttled_utilizations(nginx_ssh_client)
        
        utilization_diffs.append(get_utilization_diff(initial_utilizations, final_utilizations))

    return all_requests, utilization_diffs

def execute_parse_results(ssh_client, cmd):
    _, results, _ = ssh_client.exec_command(cmd)
    try:
        results_str = results.read()
        results_float = float(results_str.strip('\n'))
    except:
        print results.read()
        results_float = 0
    return results_float
    
#Measure response time for Spark ML-Matrix
def measure_ml_matrix(spark_args, experiment_iterations):
    all_results = {}
    all_results['latency'] = []
    
    spark_master_public_ip = spark_args[0]
    spark_master_private_ip = spark_args[1]
    ssh_client = quilt_ssh(spark_master_public_ip)
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
    print execute_spark_job

    utilization_diffs = []
    #Run the experiment experiment_iteration number of times
    for x in range(experiment_iterations):
        initial_utilizations = get_all_throttled_utilizations(ssh_client)
        print 'INITIAL UTILIZATIONS: {}'.format(initial_utilizations)
        _, runtime, _ = ssh_client.exec_command(execute_spark_job)
        print 'about to print the runtime read'
        result_time = runtime.read()
        print result_time
        try:
            runtime = int(re.findall(r'\d+',  result_time)[0])
        except IndexError:
            print 'Spark out of memory!'
            all_results['latency'].append(0)
            final_utilizations = get_all_throttled_utilizations(ssh_client)
            utilization_diffs.append(get_utilization_diff(initial_utilizations, final_utilizations))
            continue
        all_results['latency'].append(runtime)
        #Returns in milliseconds
        print 'iteration {} complete'.format(x)
        final_utilizations = get_all_throttled_utilizations(ssh_client)
        print 'FINAL UTILIZATIONS: {}'.format(final_utilizations)
        utilization_diffs.append(get_utilization_diff(initial_utilizations, final_utilizations))

    print all_results

#    numpy_all_requests = numpy.array(all_runtimes)

#   mean = numpy.mean(numpy_all_requests)
#    std = numpy.std(numpy_all_requests)
    return all_results, utilization_diffs

def measure_TODO_response_time(todo_args, iterations):
    REST_server_ip = todo_args[0]
    req_generator_ip = todo_args[1]
    
    all_requests = {}
    all_requests['rps'] = []
    all_requests['latency'] = []
    all_requests['latency_50'] = []
    all_requests['latency_99'] = []
    all_requests['latency_90'] = []

    dummy_utilizations = {}

    NUM_REQUESTS = 1500
    CONCURRENCY = 700
    ACCEPTABLE_MS = 60
    
    ssh_client = quilt_ssh(req_generator_ip)
    post_cmd = 'ab -p post.txt -T application/json -n {} -c {} -e results_file http://{}/api/todos >output.txt'.format(NUM_REQUESTS, CONCURRENCY, REST_server_ip)

    clear_cmd = 'python3 clear_entries.py'
    
    for x in range(iterations):
        _, results,_ = ssh_client.exec_command(post_cmd)
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
        
        _,cleared,_ = ssh_client.exec_command(clear_cmd)
        cleared.read()
        
    print all_requests
    return all_requests, dummy_utilizations

#Measure response time for MEAN Application
def measure_REST_response_time(REST_args, iterations):
    REST_server_ip = REST_args[0]
    ssh_server_ip = REST_args[1]
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
