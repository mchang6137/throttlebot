from remote_execution import *
from poll_cluster_state import *
import time

# Run the Spark Streaming Example
def measure_spark_streaming(workload_configurations, experiment_iterations):
    EVENTS_PER_SECOND = 3500
    EVENTS_PER_CONTAINER = 60000
    
    all_vm_ip = get_actual_vms()
    print 'Collecting information about service/deployment'
    service_to_deployment = get_service_placements(all_vm_ip)

    generator_instances = service_to_deployment['mchang6137/spark_streaming']
    kafka_instances = service_to_deployment['mchang6137/kafka']
    redis_instances = service_to_deployment['hantaowang/redis']
    spark_master_instances = service_to_deployment['mchang6137/spark-yahoo-master']
    spark_worker_instances = service_to_deployment['mchang6137/spark-yahoo-worker']

    all_requests = {}
    all_requests['latency_50'] = []
    all_requests['latency_75'] = []
    all_requests['latency_99'] = []
    all_requests['latency_95'] = []
    all_requests['latency_100'] = []
    all_requests['window_latency_std'] = []
    all_requests['total_results'] = []
    
    # Initialization
    stop_spark_job(spark_master_instances)
    clean_files(generator_instances)
    flush_redis(redis_instances)
    start_spark_job(spark_master_instances)
    
    stop_spark_job(spark_master_instances)
    start_spark_job(spark_master_instances)
    
    # Warmup JVM
    warmup_count = 0
    while warmup_count < 1:
        run_kafka_events(generator_instances, 1000, 10000)
        results = collect_results(generator_instances, redis_instances, 10000)
        if results is None:
            stop_spark_job(spark_master_instances)
            start_spark_job(spark_master_instances)
            stop_spark_job(spark_master_instances)
            start_spark_job(spark_master_instances)
            continue
        clean_files(generator_instances)
        flush_redis(redis_instances)
        warmup_count += 1

    # Run the Experiment 
    trial_count = 0
    while trial_count < experiment_iterations:
        run_kafka_events(generator_instances, EVENTS_PER_SECOND, EVENTS_PER_CONTAINER)
        print 'Attempting to collect results\n'
        results = collect_results(generator_instances, redis_instances, EVENTS_PER_CONTAINER)
        if results is None:
            stop_spark_job(spark_master_instances)
            start_spark_job(spark_master_instances)
            stop_spark_job(spark_master_instances)
            start_spark_job(spark_master_instances)
            continue
        # Clean up Files and collect results
        clean_files(generator_instances)
        all_requests['window_latency_std'].append(results['window_latency_std'])
        all_requests['total_results'].append(results['total_results'])
        all_requests['latency_50'].append(results['latency_50'])
        all_requests['latency_75'].append(results['latency_75'])
        all_requests['latency_100'].append(results['latency_100'])
        all_requests['latency_99'].append(results['latency_99'])
        all_requests['latency_95'].append(results['latency_95'])

        flush_redis(redis_instances)
        trial_count += 1

    print 'Results from this experiment are {}'.format(all_requests)
    stop_spark_job(spark_master_instances)
    print 'Stopped Spark'
    delete_spark_logs(spark_master_instances, spark_worker_instances)

    return all_requests

def start_spark_job(spark_master_instances):
    print 'Starting Spark job\n'
    vm_ip,container_id = spark_master_instances[0]
    start_spark_cmd = 'bash -c "spark-submit --executor-memory 2g --class de.codecentric.spark.streaming.example.spark-submit --class de.codecentric.spark.streaming.example.YahooStreamingBenchmark --master spark://spark-ms2.q:7077 --conf spark.executor.extraClassPath=/spark-streaming-example/target/spark-streaming-example-assembly-2f7c377ab4c00e30255ebf55e24102031122f358-SNAPSHOT.jar --deploy-mode client spark-streaming-example/target/spark-streaming-example-assembly-2f7c377ab4c00e30255ebf55e24102031122f358-SNAPSHOT.jar kafka_broker0.q:9092 ad-events redis-ms.q 1000"'
    ssh_client = get_client(vm_ip)
    run_cmd(start_spark_cmd, ssh_client, container_id, blocking=False, lein=False)
    time.sleep(120)
    ssh_client.close()

def stop_spark_job(spark_master_instances):
    print 'Stopping Spark job\n'
    vm_ip,container_id = spark_master_instances[0]
    
    stop_spark_cmd = "ps -ef | grep java | grep YahooStreamingBenchmark | awk '{print \$2}' | xargs kill -SIGTERM"
    stop_spark_cmd = 'bash -c "' + stop_spark_cmd + '"'
    ssh_client = get_client(vm_ip)
    run_cmd(stop_spark_cmd, ssh_client, container_id, blocking=False, lein=True)
    ssh_client.close()
    time.sleep(15)

# Need this when the requests get too misaligned
def all_reset(kafka_instances,redis_instances):
    # Flush Queus
    flush_kafka_queues(kafka_instances)

    # Wait 5 minutes to allow for catching up
    time.sleep(300)

    # Flush Redis DB
    flush_redis(redis_instances)
    

def flush_kafka_queues(kafka_instances):
    for kafka_instance in kafka_instances:
        kafka_ip,kafka_container = kafka_instance
        kafka_client = get_client(kafka_ip)
        
        # Set a low retention time on the logs
        low_retention_cmd = 'bash -c "./opt/kafka_2.11-0.10.1.0/bin/kafka-configs.sh --zookeeper localhost:2181 --entity-type topics --alter --add-config retention.ms=1000 --entity-name ad-events"'
        run_cmd(low_retention_cmd, kafka_client, kafka_container, blocking=True, lein=False)

        # Sleep for some amount of time
        time.sleep(90)
        reset_retention_cmd = 'bash -c "./opt/kafka_2.11-0.10.1.0/bin/kafka-configs.sh --zookeeper localhost:2181 --entity-type topics --alter --delete-config retention.ms  --entity-name ad-events"'
        run_cmd(reset_retention_cmd, kafka_client, kafka_container, blocking=True, lein=False)
        time.sleep(30)

# Delete spark logs so it doesn't run out of data
def delete_spark_logs(spark_master_instances, spark_worker_instances):
    delete_wk_logs_cmd = 'bash -c "rm -r /spark/work/app*"'
    delete_ms_logs_cmd = 'bash -c "rm /spark/logs/spark.log"'
    
    for spark_instance in spark_worker_instances:
        spark_ip,spark_container = spark_instance
        spark_client = get_client(spark_ip)
        run_cmd(delete_wk_logs_cmd, spark_client, spark_container, blocking=True, lein=False)
        run_cmd(delete_ms_logs_cmd, spark_client, spark_container, blocking=True, lein=False)
        spark_client.close()

    for spark_instance in spark_master_instances:
        spark_ip,spark_container = spark_instance
        spark_client = get_client(spark_ip)
        run_cmd(delete_wk_logs_cmd, spark_client, spark_container, blocking=True, lein=False)
        run_cmd(delete_ms_logs_cmd, spark_client, spark_container, blocking=True, lein=False)
        spark_client.close()
    
# Parse_results script parses results from updated.txt and seen.txt before removing the files so as to not corrupt future experiments
def collect_results(instances, redis_instances, events_per_container):
    # Number of events that are sent among all producer instances
    total_num_events = events_per_container * len(instances)

    # Only need to collect results from one instance
    send_events_ip,send_events_container = instances[0]
    print 'DEBUG: Collecting results from {}'.format(send_events_container)
    ssh_client = get_client(send_events_ip)
    results = {}

    attempts_required = 10

    for attempt in range(attempts_required):
        print 'Attempt number {}\n'.format(attempt)
        # Clean the results of the file from the old experiment
        clean_files(instances)
        
        # Collect the results
        lein_collect_cmd = 'bash -c "cd /streaming-benchmarks/data && /bin/lein run -g --configPath /streaming-benchmarks/conf/localConf.yaml"'
        run_cmd(lein_collect_cmd, ssh_client, send_events_container, blocking=True, lein=False)
        time.sleep(10)

        # Parse the results
        parse_results_cmd = 'bash -c "cd /streaming-benchmarks/data && sh parse_results.sh"'
        run_cmd(parse_results_cmd, ssh_client, send_events_container, blocking=True, lein=False)

        # Copy files into host machine
        copy_data_cmd = 'docker cp {}:/streaming-benchmarks/data/latency.txt . && cat latency.txt'.format(send_events_container)
        _,data_exec,_ = ssh_client.exec_command(copy_data_cmd)
        data = data_exec.read()

        clean_files(instances)
        print 'INFO: Collected results are {}\n'.format(repr(data))
        latency_50,latency_75,latency_95,latency_99,latency_100,std,total_results,_ = data.split('\n')
        results_seen = float(total_results.split(': ')[1])

        if results_seen != total_num_events:
            print 'Events seen: {}, Expected Events: {}\n'.format(results_seen, total_num_events)
            # Sleep for 15 seconds and wait for future results
            time.sleep(15)
            continue
        else:
            results['latency_50'] = float(latency_50.split(': ')[1])
            results['latency_75'] = float(latency_75.split(': ')[1])
            results['latency_95'] = float(latency_95.split(': ')[1])
            results['latency_99'] = float(latency_99.split(': ')[1])
            results['latency_100'] = float(latency_100.split(': ')[1])
            results['window_latency_std'] = float(std.split(': ')[1])
            results['total_results'] = results_seen
            print 'All results received. Results are as follows: {}\n'.format(results)
            return results
        
    print "Error: Something bad happened, so we need to flush out all the old messages"
    print "This will cause skew, so let's try a few things!"
    flush_redis(redis_instances)
    
    # This presumably caused some something to crash so let's set this arbitrarily high
    # Set the other two fields as zero
    return None

def clean_files(instances):
    for instance in instances:
        send_events_ip,send_events_container = instance
        ssh_client = get_client(send_events_ip)
    
        # Delete the latency.txt for safe-keeping
        clean_file_cmd = 'bash -c "rm /streaming-benchmarks/data/latency.txt && rm -f /streaming-benchmarks/data/seen.txt && rm -f /streaming-benchmarks/data/updated.txt"'
        run_cmd(clean_file_cmd, ssh_client, send_events_container, blocking=True, lein=False)
        ssh_client.close()

# send_events_instances sends from instances in the list, where each instance is (vm_ip, container_id)
def run_kafka_events(send_event_instances, events_per_second, events_per_container):
    assert len(send_event_instances) > 0
    
    # Initializes Data in Redis
    create_data_cmd = 'bash -c "cd /streaming-benchmarks/data && /bin/lein run -n --configPath ../conf/localConf.yaml"'
    # Start Sending Data
    send_event_cmd = 'bash -c "cd /streaming-benchmarks/data && /bin/lein run -r -t {} -b {} --configPath ../conf/localConf.yaml"'.format(events_per_second, events_per_container)

    first_instance_ip,first_instance_id = send_event_instances[0]
    ssh_client = get_client(first_instance_ip)
    run_cmd(create_data_cmd, ssh_client, first_instance_id, blocking=True, lein=False)
    time.sleep(10)
    
    for instance in send_event_instances:
        vm_ip,container_id = instance
        ssh_client = get_client(vm_ip)
        run_cmd(send_event_cmd, ssh_client, container_id, blocking=False, lein=True)
        ssh_client.close()

    # Sleep to finish sending events. Will require even more time to process.
    time.sleep(events_per_container/events_per_second)

def flush_redis(redis_instances):
    for redis_instance in redis_instances:
        redis_ip,redis_container = redis_instance
        
        # Set up clients
        redis_client = get_client(redis_ip)
        # Flush redis db
        run_cmd("redis-cli flushdb", redis_client, redis_container, True, False)
        redis_client.close()

def run_cmd(cmd, cli, cid, blocking=False, lein=False):
    if lein:
        optargs = "--env LEIN_ROOT=true -i"
    else:
        optargs = ""
    run = "docker exec {} {} {}".format(optargs, cid, cmd)
    if blocking:
        stdin, stdout, stderr = cli.exec_command(run)
        stderr.read()
    else:
        _, _, _ = cli.exec_command("docker exec {} {} {}".format(optargs, cid, cmd))

if __name__ == '__main__':
    trials = 1
    workload_config = {}
    workload_config['spark-master'] = '54.219.132.191'
    measure_spark_streaming(workload_config, trials)
    
    
        
