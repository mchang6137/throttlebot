from remote_execution import *
from poll_cluster_state import *
import time

SENDING_TIME = 30
EVENTS_PER_SEC=3000

# Run the Spark Streaming Example
def measure_spark_streaming(workload_configurations, experiment_iterations):
    all_vm_ip = get_actual_vms()
    print 'Collecting information about service/deployment'
    service_to_deployment = get_service_placements(all_vm_ip)

    generator_instances = service_to_deployment['mchang6137/spark_streaming']
    kafka_instances = service_to_deployment['mchang6137/kafka']
    redis_instances = service_to_deployment['hantaowang/redis']
    spark_master_instances = service_to_deployment['mchang6137/spark-yahoo-master']
    spark_worker_instances = service_to_deployment['mchang6137/spark-yahoo-worker']
    
    all_requests = {}
    all_requests['window_latency'] = []
    all_requests['window_latency_std'] = []
    all_requests['total_results'] = []

    trial_count = 0 
    # Initialize the Spark Streaming Job
    while trial_count < experiment_iterations:
        clean_files(generator_instances)
        # Start Sending Timed events through Kafka
        run_kafka_events(generator_instances)
        
        # Collect the results of the experiment
        results = collect_results(generator_instances)

        if results is None:
            print 'Result is none... retrying experiment'
            
            # One reason for this is that the results have not yet been collected.
            for x in range(3):
                results = collect_results(generator_instances)
                if results != None:
                    trial_count += 1
                    break
        else:
            trial_count += 1

        # If results are still none, continue
        if results is None:
            continue

        clean_files(generator_instances)
        all_requests['window_latency'].append(results['window_latency'])
        all_requests['window_latency_std'].append(results['window_latency_std'])
        all_requests['total_results'].append(results['total_results'])

        flush_redis(redis_instances)

    #delete_spark_logs(spark_master_instances, spark_worker_instances)

    return all_requests

# Delete spark logs so it doesn't run out of data
def delete_spark_logs(spark_master_instances, spark_worker_instances):
    delete_wk_logs_cmd = 'rm -r /spark/work/app*'
    delete_ms_logs_cmd = 'rm /spark/logs/spark.log'
    
    for spark_instance in spark_worker_instances:
        spark_ip,spark_container = spark_instance
        spark_client = get_client(spark_ip)
        run_cmd(delete_wk_logs_cmd, spark_client, spark_container, blocking=True, lein=False)
        run_cmd(delete_ms_logs_cmd, spark_client, spark_container, blocking=True, lein=False)

    for spark_instance in spark_master_instances:
        spark_ip,spark_container = spark_instance
        spark_client = get_client(spark_ip)
        run_cmd(delete_wk_logs_cmd, spark_client, spark_container, blocking=True, lein=False)
        run_cmd(delete_ms_logs_cmd, spark_client, spark_container, blocking=True, lein=False)
    
# Parse_results script parses results from updated.txt and seen.txt before removing the files so as to not corrupt future experiments
def collect_results(instances):
    send_events_ip,send_events_container = instances[0]
    ssh_client = get_client(send_events_ip)
    results = {}

    # Get the results
    lein_collect_cmd = 'bash -c "cd /streaming-benchmarks/data && /bin/lein run -g --configPath /streaming-benchmarks/conf/localConf.yaml"'.format(send_events_container)
    run_cmd(lein_collect_cmd, ssh_client, send_events_container, blocking=True, lein=False)
    time.sleep(10)

    # Parse the results
    parse_results_cmd = 'bash -c "cd /streaming-benchmarks/data && sh parse_results.sh"'.format(send_events_container)
    run_cmd(parse_results_cmd, ssh_client, send_events_container, blocking=True, lein=False)

    # Copy files into host machine
    copy_data_cmd = 'docker cp {}:/streaming-benchmarks/data/latency.txt . && cat latency.txt'.format(send_events_container)
    _,data_exec,_ = ssh_client.exec_command(copy_data_cmd)
    data = data_exec.read()

    print 'INFO: Collected results are {}'.format(repr(data))
    
    average_latency,latency_std,nsum,_ = data.split('\n')
    results['window_latency'] = float(average_latency.split(': ')[1])
    results['window_latency_std'] = float(latency_std.split(': ')[1])
    results['total_results'] = float(nsum.split(': ')[1])/float(SENDING_TIME)
    # Check if the files were empty and not cleanly generated
    if results['window_latency'] == -1 or results['total_results'] == -1:
        print 'ERROR: Latency values were not generated correctly'
        return None
    print 'Results of Experiment are {}'.format(results)
    return results

def clean_files(instances):
    send_events_ip,send_events_container = instances[0]
    ssh_client = get_client(send_events_ip)
    
    # Delete the latency.txt for safe-keeping
    clean_file_cmd = 'bash -c "rm /streaming-benchmarks/data/latency.txt && rm -f /streaming-benchmarks/data/seen.txt && rm -f /streaming-benchmarks/data/updated.txt"'
    run_cmd(clean_file_cmd, ssh_client, send_events_container, blocking=True, lein=False)

# send_events_instances sends from instances in the list, where each instance is (vm_ip, container_id)
def run_kafka_events(send_event_instances):
    assert len(send_event_instances) > 0
    
    # Initializes Data in Redis
    create_data_cmd = 'bash -c "cd /streaming-benchmarks/data && /bin/lein run -n --configPath ../conf/localConf.yaml"'
    # Start Sending Data
    send_event_cmd = 'bash -c "cd /streaming-benchmarks/data && timeout {}s /bin/lein run -r -t {} --configPath ../conf/localConf.yaml"'.format(SENDING_TIME, EVENTS_PER_SEC)

    first_instance_ip,first_instance_id = send_event_instances[0]
    ssh_client = get_client(first_instance_ip)
    run_cmd(create_data_cmd, ssh_client, first_instance_id, blocking=True, lein=False)
    time.sleep(10)
    
    for instance in send_event_instances:
        vm_ip,container_id = instance
        ssh_client = get_client(vm_ip)
        run_cmd(send_event_cmd, ssh_client, container_id, blocking=False, lein=True)
        ssh_client.close()

    time.sleep(SENDING_TIME)

def flush_redis(redis_instances):
    for redis_instance in redis_instances:
        redis_ip,redis_container = redis_instance
        
        # Set up clients
        redis_client = get_client(redis_ip)
        # Flush redis db
        run_cmd("redis-cli flushdb", redis_client, redis_container, True, False)
        redis_client.close()

commands = {"set_kafka": "/opt/kafka_2.11-0.10.1.0/bin/kafka-topics.sh --zookeeper kafka_host.q --create --replication-factor 1 --partitions 1 --topic ad-events",
"spark-submit": "spark-submit --class de.codecentric.spark.streaming.example.spark-submit --class de.codecentric.spark.streaming.example.YahooStreamingBenchmark --master spark://spark-ms2.q:7077 --conf spark.executor.extraClassPath=/spark-streaming-example/target/spark-streaming-example-assembly-2f7c377ab4c00e30255ebf55e24102031122f358-SNAPSHOT.jar --deploy-mode cluster spark-streaming-example/target/spark-streaming-example-assembly-2f7c377ab4c00e30255ebf55e24102031122f358-SNAPSHOT.jar kafka_broker0.q:9092 ad-events redis_master.q 1000",
"start_exp": "bash -c 'cd /streaming-benchmarks/data && /bin/lein run -n --configPath ../conf/localConf.yaml && sleep 5 && timeout {}s /bin/lein run -r -t {} --configPath ../conf/localConf.yaml'".format(SENDING_TIME, EVENTS_PER_SEC),
"init_exp": "timeout {}s /bin/lein run -r -t {} --config Path ../conf/localConf.yaml'".format(SENDING_TIME, EVENTS_PER_SEC),
"collect_results": "/bin/lein run -g --configPath ../conf/localConf.yaml || true",
"clear_kafka_1":  "/opt/kafka_2.11-0.10.1.0/bin/kafka-topics.sh --zookeeper kafka_host.q --alter --topic ad-events --config retention.ms=1000",
"clear_kafka_2": "/opt/kafka_2.11-0.10.1.0/bin/kafka-topics.sh --zookeeper kafka_host.q --alter --topic ad-events --delete-config retention.ms"
}


def run_cmd(cmd, cli, cid, blocking=False, lein=False):
    if lein:
        optargs = "--env LEIN_ROOT=true -i"
    else:
        optargs = ""
    run = "docker exec {} {} {}".format(optargs, cid, cmd)
    print 'Experiment Debug: {}'.format(run)
    if blocking:
        stdin, stdout, stderr = cli.exec_command(run)
        print stderr.read()
    else:
        _, _, _ = cli.exec_command("docker exec {} {} {}".format(optargs, cid, cmd))

if __name__ == '__main__':
    trials = 1
    workload_config = {}
    workload_config['spark-master'] = '54.219.132.191'
    measure_spark_streaming(workload_config, trials)
    
    
        
