import argparse
import requests
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import datetime
import numpy
import time
import subprocess
import paramiko
import csv
from multiprocessing.dummy import Pool as ThreadPool

import logging

REST_URL = '/api/todos'

REMOTE_POST_SCRIPT = "remote_make_post.py"
CONFIG_SCRIPT = "config_vm"
RESULT_FNAME = "times.csv"

def POST_to_website(website_ip, num_iterations, num_threads=4, remote=False, ssh_ip=""):
    if remote:
        scp_upload = "scp -oStrictHostKeyChecking=no {} {} quilt@{}:~".format(REMOTE_POST_SCRIPT, CONFIG_SCRIPT, ssh_ip)
        subprocess.call(scp_upload, shell=True)

        ssh_client = get_client(ssh_ip)
        config_cmd = "chmod +x {c} && ./{c}".format(c=CONFIG_SCRIPT)
        measure_cmd = "python3 {} {} --iterations {} --threads {}".format(REMOTE_POST_SCRIPT, website_ip, num_iterations, num_threads)
        ssh_exec(ssh_client, config_cmd)
        ssh_exec(ssh_client, measure_cmd)

        scp_download = "scp -oStrictHostKeyChecking=no quilt@{}:~/{} .".format(ssh_ip, RESULT_FNAME)
        subprocess.call(scp_download, shell=True)

        with open(RESULT_FNAME, "r") as f:
            reader = csv.reader(f)
            all_request_times = next(reader)
            return [float(t) for t in all_request_times]
    else:
        requests = [website_ip] * num_iterations
        pool = ThreadPool(num_threads)
        all_request_times = pool.map(make_single_POST, requests)
    return all_request_times

def ssh_exec(ssh_client, cmd):
    _, _, stderr = ssh_client.exec_command(cmd)
    err = stderr.read()
    if err:
        logging.info("Error execing {}: {}".format(cmd, err))

def get_client(ip):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(ip, username="quilt", password="")
    return client

def make_single_POST(website_ip):
    url = 'http://' + website_ip + REST_URL
    current_date = datetime.datetime.now()
    data = {'text': str(current_date)}
    headers = {'Content-type': 'application/json'}
    request_time = requests.post(url, data=json.dumps(data), headers=headers).elapsed.total_seconds()
    return request_time

def delete_posts(website_ip, all_ids):
    url = 'http://' + website_ip + REST_URL + '/'
    for ids in all_ids:
        requests.delete(url + ids)

def GET_from_website(website_ip):
    url = 'http://' + website_ip + REST_URL
    r = requests.get(url).json()
    all_request_ids = []
    for request in r:
        all_request_ids.append(request['_id'])
    return all_request_ids


def clear_all_entries(website_ip):
    all_ids = GET_from_website(website_ip)
    delete_posts(website_ip, all_ids)

def plot_requests(request_measurements):
    fig = plt.hist(request_measurements)
    # plt.show()
    plt.savefig("plot.png")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("website_ip")
    parser.add_argument("--iterations", type=int, default=100, help="Number of HTTP requests to send the REST server")
    parser.add_argument("--threads", type=int, default=4, help="Number of threads used to execute the HTTP requests")
    parser.add_argument("--network_delay", type=float, default=-1.0, help="Network delay in milliseconds.")
    parser.add_argument("--rm_network_delay", action="store_true", help="Remove any artificial network delays.")
    parser.add_argument("--cpu_limit", type=float, default=-1.0, help="Limit CPU at CPU_LIMIT * 100 percent.")
    parser.add_argument("--mem_limit", type=float, default=-1.0, help="Limit memory at MEM_LIMIT * 100 percent.")
    args = parser.parse_args()

    t0 = time.time()
    all_requests = POST_to_website(args.website_ip, args.iterations, args.threads)
    t1 = time.time()
    numpy_all_requests = numpy.array(all_requests)
    mean = numpy.mean(numpy_all_requests)
    std = numpy.std(numpy_all_requests)
    plot_requests(all_requests)

    # Clear all entries after running
    clear_all_entries(args.website_ip)

    print('Mean: ' + str(mean))
    print('Std: ' + str(std))

    elapsed = t1 - t0
    print("Time spent: " + str(elapsed))
    print("req/s = " + str(args.iterations / elapsed))
