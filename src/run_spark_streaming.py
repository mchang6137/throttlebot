from remote_execution import *
import time

def measure_spark_streaming(container_id, experiment_args, experiment_iteration):    
    results = run_iteration(experiment_args)
    reset_queue(experiment_args)
    return results

def run_iteration(experiment_args):
    #Amount of time to run spark streaming job
    EXP_TIME = 130
    
    # Set up clients
    spark = get_client(experiment_args["mchang6137/spark-yahoo"][0])
    stream = get_client(experiment_args["mchang6137/spark_streaming"][0])

    # Spark Submit
    run_cmd(commands["spark-submit"], spark, experiment_args["mchang6137/spark-yahoo"][1], True, False)

    # Runs the lein experiement
    run_cmd(commands["start_exp"], stream, experiment_args["mchang6137/spark_streaming"][1], False, True)
    print "sleep 130"
    time.sleep(EXP_TIME)

    # Collects the results
    run_cmd(commands["collect_results"], stream, experiment_args["mchang6137/spark_streaming"][1], True, True)
    print "sleep 10"
    time.sleep(10)

    # parse_results script parses results from updated.txt and seen.txt before removing the files so as to not corrupt future experiments
    results = {}
    parse_results_cmd = '''docker exec -i {} bash -c "cd /streaming-benchmarks/data && sh parse_results.sh"'''.format(experiment_args["stream"][1])
    _,data_exec,_ = stream.exec_command(parse_results_cmd)
    data = results_exec.read()
    average_latency,latency_std,nsum,_ = data.split('\n')
    results['window_latency'] = int(average_latency.split(': ')[1])
    results['window_latency_std'] = int(latency_std.split(': ')[1])
    results['total_results'] = int(nsum.split(': ')[1])

    #Check if the files were empty and not cleanly generated
    if results['window_latency'] == -1 or results['total_results'] == -1:
        #Return an invalid result
        print 'ERROR: Latency values were not generated correctly'

    # Close the tunnels.
    spark.close()
    stream.close()

    return results


def reset_queue(experiment_args):
    # Set up clients
    redis = get_client(experiment_args["hantaowang/redis"][0])
    kafka = get_client(experiment_args["mchang6137/kafka"][0])
    stream = get_client(experiment_args["mchang6137/spark_streaming"][0])

    # Remove updated and seen
    run_cmd("rm /streaming-benchmarks/data/seen.txt", stream, experiment_args["mchang6137/spark_streaming"][1], True, False)
    run_cmd("rm /streaming-benchmarks/data/updated.txt", stream, experiment_args["mchang6137/spark_streaming"][1], True, False)

    # Flush redis db
    run_cmd("redis-cli flushdb", redis, experiment_args["hantaowang/redis"][1], True, False)

    #run kafka commands
    run_cmd(commands["clear_kafka_1"], kafka, experiment_args["mchang6137/kafka"][1], True, False)
    print "sleep 90"
    time.sleep(90)
    run_cmd(commands["clear_kafka_2"], kafka, experiment_args["mchang6137/kafka"][1], True, False)

    # Close tunnels
    redis.close()
    kafka.close()
    stream.close()


commands = {"set_kafka": "/opt/kafka_2.11-0.10.1.0/bin/kafka-topics.sh --zookeeper kafka_host.q --create --replication-factor 1 --partitions 1 --topic ad-events",
"spark-submit": "spark-submit --class de.codecentric.spark.streaming.example.spark-submit --class de.codecentric.spark.streaming.example.YahooStreamingBenchmark --master spark://spark-master.0.q:7077 --conf spark.executor.extraClassPath=/spark-streaming-example/target/spark-streaming-example-assembly-2f7c377ab4c00e30255ebf55e24102031122f358-SNAPSHOT.jar --deploy-mode cluster spark-streaming-example/target/spark-streaming-example-assembly-2f7c377ab4c00e30255ebf55e24102031122f358-SNAPSHOT.jar kafka_host.q:9092 ad-events redis_master.q 1",
"start_exp": "bash -c 'cd /streaming-benchmarks/data && /bin/lein run -n --configPath ../conf/localConf.yaml && sleep 5 && timeout 120s /bin/lein run -r -t 100 --configPath ../conf/localConf.yaml'",
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

