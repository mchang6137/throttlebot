from remote_execution import *
import time

SENDING_TIME = 120
EVENTS_PER_SEC=10000

def measure_spark_streaming(container_id, experiment_args, experiment_iteration):
    results = run_iteration(experiment_args[0])
    reset_queue(experiment_args[0])
    return results

#Submit first Spark Job and run the throughput job for arbitrary amount of time; these results are discarded
def initialize_spark_experiment(experiment_args):
    print experiment_args
    # Spark Submit
    spark = get_client(experiment_args["mchang6137/spark-yahoo"][0][0])
    run_cmd(commands["spark-submit"], spark, experiment_args["mchang6137/spark-yahoo"][0][1], True, False)
    print 'INFO: Spark Master has been started'
    time.sleep(20)
    spark.close()

    #Run Initial Experiment
    stream = get_client(experiment_args["mchang6137/spark_streaming"][0][0])
    #is_initialize should be false so the database is also initialized
    run_kafka_events(stream, experiment_args, is_initialize=False)
    
    while True:
        run_kafka_events(stream, experiment_args, is_initialize=True)
        results = collect_results(stream, experiment_args)
        print 'INFO: Prep Time -- waited 120 seconds, checking results'
        print results
        if results['window_latency'] != -1:
            break

    print 'INFO: Initialization completed. Can start actual experiments'
    
def run_iteration(experiment_args):
    # Set up clients
    stream = get_client(experiment_args["mchang6137/spark_streaming"][0][0])

    run_kafka_events(stream, experiment_args)
    results = collect_results(stream, experiment_args)

    # Close the tunnels.
    stream.close()

    return results

# Parse_results script parses results from updated.txt and seen.txt before removing the files so as to not corrupt future experiments
def collect_results(stream, experiment_args):
    results = {}
    parse_results_cmd = '''docker exec -i {} bash -c "cd /streaming-benchmarks/data && sh parse_results.sh"'''.format(experiment_args["mchang6137/spark_streaming"][0][1])
    _,data_exec,_ = stream.exec_command(parse_results_cmd)
    data = data_exec.read()
    average_latency,latency_std,nsum,_ = data.split('\n')
    results['window_latency'] = int(average_latency.split(': ')[1])
    results['window_latency_std'] = int(latency_std.split(': ')[1])
    results['total_results'] = int(nsum.split(': ')[1])/float(SENDING_TIME)

    #Check if the files were empty and not cleanly generated
    if results['window_latency'] == -1 or results['total_results'] == -1:
        #Return an invalid result
        print 'ERROR: Latency values were not generated correctly'

    return results

def run_kafka_events(stream, experiment_args, is_initialize=False):
    # Runs the lein experiement
    if is_initialize is False:
        run_cmd(commands["start_exp"], stream, experiment_args["mchang6137/spark_streaming"][0][1], False, True)
    else:
        run_cmd(commands["init_exp"], stream, experiment_args["mchang6137/spark_streaming"][0][1], False, True)
    print "sleep {}".format(SENDING_TIME)
    time.sleep(SENDING_TIME)

    # Collects the results
    run_cmd(commands["collect_results"], stream, experiment_args["mchang6137/spark_streaming"][0][1], True, True)
    print "sleep 10"
    time.sleep(10)


def reset_queue(experiment_args):
    # Set up clients
    redis = get_client(experiment_args["hantaowang/redis"][0][0])
    kafka = get_client(experiment_args["mchang6137/kafka"][0][0])
    stream = get_client(experiment_args["mchang6137/spark_streaming"][0][0])

    # Remove updated and seen
    #run_cmd("rm /streaming-benchmarks/data/seen.txt", stream, experiment_args["mchang6137/spark_streaming"][0][1], True, False)
    #run_cmd("rm /streaming-benchmarks/data/updated.txt", stream, experiment_args["mchang6137/spark_streaming"][0][1], True, False)

    # Flush redis db
    run_cmd("redis-cli flushdb", redis, experiment_args["hantaowang/redis"][0][1], True, False)

    #run kafka commands
    run_cmd(commands["clear_kafka_1"], kafka, experiment_args["mchang6137/kafka"][0][1], True, False)
    print "sleep 90"
    time.sleep(90)
    run_cmd(commands["clear_kafka_2"], kafka, experiment_args["mchang6137/kafka"][0][1], True, False)

    # Close tunnels
    redis.close()
    kafka.close()
    stream.close()


commands = {"set_kafka": "/opt/kafka_2.11-0.10.1.0/bin/kafka-topics.sh --zookeeper kafka_host.q --create --replication-factor 1 --partitions 1 --topic ad-events",
"spark-submit": "spark-submit --class de.codecentric.spark.streaming.example.spark-submit --class de.codecentric.spark.streaming.example.YahooStreamingBenchmark --master spark://spark-master.0.q:7077 --conf spark.executor.extraClassPath=/spark-streaming-example/target/spark-streaming-example-assembly-2f7c377ab4c00e30255ebf55e24102031122f358-SNAPSHOT.jar --deploy-mode cluster spark-streaming-example/target/spark-streaming-example-assembly-2f7c377ab4c00e30255ebf55e24102031122f358-SNAPSHOT.jar kafka_host.q:9092 ad-events redis_master.q 1000",
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
    print run
    if blocking:
        stdin, stdout, stderr = cli.exec_command(run)
        print stderr
    else:
        _, _, _ = cli.exec_command("docker exec {} {} {}".format(optargs, cid, cmd))

