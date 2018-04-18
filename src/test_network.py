from poll_cluster_state import *
from remote_execution import *
from modify_resources import set_egress_network_bandwidth

all_vm_ip = get_actual_vms()
service_to_deployment = get_service_placements(all_vm_ip)

# Memwall is just a filler image to run. Doesn't actually do anything as long as you don't hit the endpoint.
IMAGE_NAME = 'hantaowang/memwall:latest'
TEST_PERIOD = 60  # Seconds to test for
TRIALS = 3  # Number of trials to run

# (ip, cont_id)
client_container = service_to_deployment[IMAGE_NAME][0]
server_container = service_to_deployment[IMAGE_NAME][1]

# Commands to run
client_command = "iperf -c {0} -t {1} --reportstyle C"
server_command = "iperf -s"
docker_command = 'docker exec {0} sh -c "{1}"'
apt_get_command = "apt-get install iperf --yes"


def run_server(server):
    ssh_client = get_client(server[0])
    _, results, error = ssh_client.exec_command(
        docker_command.format(server[1], server_command))
    print "Server running."


def find_server_name(client):
    if run_trial(client, "memwall.q") == -1:
        return "memwall2.q"
    return "memwall.q"


def run_trial(client, connection):
    ssh_client = get_client(client[0])
    _, results, error = ssh_client.exec_command(
        docker_command.format(client[1], client_command.format(connection, TEST_PERIOD)))
    results_str = results.read()
    close_client(ssh_client)
    if "failed" in results_str or len(results_str) == 0:
        return -1
    else:
        bps = int(results_str.split(",")[-1])
        mbps = bps / (1024 * 1024)
        return mbps


def setup_iperf(client, server):
    ssh_client = get_client(client[0])
    _, results, error = ssh_client.exec_command(
        docker_command.format(client[1], apt_get_command))
    results.channel.recv_exit_status()
    close_client(ssh_client)
    print "Iperf installed on client"

    ssh_client = get_client(server[0])
    _, results, error = ssh_client.exec_command(
        docker_command.format(server[1], apt_get_command))
    results.channel.recv_exit_status()
    close_client(ssh_client)
    print "Iperf installed on server"


def run_experiment(client, server, connection):
    trials = []
    for i in range(TRIALS):
        result = run_trial(client, connection)
        if result == -1:
            return -1
        print "Trial {0} of {1}: {2} Mbits/sec".format(i+1, TRIALS, result)
        trials.append(result)
    return sum(trials)/len(trials)


def compare(result, baseline, error=0.02):
    if result < baseline * (1 - error):
        return 1
    else:
        return 0


def stress(client, mbps):
    ssh_client = get_client(client[0])
    set_egress_network_bandwidth(ssh_client, client[1], mbps * 1024)
    close_client(ssh_client)


def ascend(start, step, target, iteration, connection):
    results = 0
    cap = start
    while compare(results, target):
        print "-------- Iteration {0} --------".format(iteration)
        print "Set cap to {0} Mbits/sec".format(cap)
        stress(client_container, cap)
        results = run_experiment(client_container, server_container, connection)
        print "Iperf results: {0} Mbits/sec".format(results)
        iteration += 1
        cap += step
    return cap - step, iteration


def main():
    setup_iperf(client_container, server_container)
    run_server(server_container)
    connection = find_server_name(client_container)
    baseline = run_experiment(client_container, server_container, connection)
    print "Baseline: {0}".format(baseline)

    step = 200
    cap = baseline - baseline % 25
    iteration = 0
    while step >= 25:
        cap, iteration = ascend(cap, step, baseline, iteration, connection)
        if step / 2 < 25:
            break
        cap = cap - step
        step = step / 2

    print "-------- RESULTS --------".format(iteration)
    print "Set network cap to {0} Mbits/sec".format(cap)


"""
To run, run the network.js script in throttlebot-specs/utilization_specs/network_test.
Change the machine type to the type you would like to test. Wait until containers boot.
Then just run this script, sit back, and wait.
"""
if __name__ == "__main__":
    main()