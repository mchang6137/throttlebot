from stress_analyzer import *
from remote_execution import *
from run_spark_streaming import *
import argparse

import logging

def print_ip_to_container_id(services_to_stress, dictionary_ip_cont):
    logging.info(dictionary_ip_cont)
    for service in services_to_stress:
        results = dictionary_ip_cont[service]
        for container in results:
            logging.info('{},{},'.format(container[0], container[1]))

def start_experiments(dictionary_ip_cont):
    sending_time = 200
    service_name = 'mchang6137/spark_streaming'
    container_list = dictionary_ip_cont[service_name]
    #start_exp_cmd = 'cd /streaming-benchmarks/data && timeout {}s /bin/lein run -r -t {} --configPath ../conf/localConf.yaml'.format(sending_time, 15000)
    start_exp_cmd = 'sleep 10'
    for container in container_list:
        ip,container_id = container
        client = get_client(ip)
        run_cmd(start_exp_cmd, client, container_id, False, True)
    logging.info('All experiments started')
    time.sleep(sending_time)
    logging.info('All experiments completed -- collect results on any machine')

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("public_vm_ips")
    parser.add_argument("services_to_stress")
    args = parser.parse_args()

    public_vm_ips = args.public_vm_ips.split(',')
    services_to_stress = args.services_to_stress.split(',')

    dictionary_ip_cont = get_container_ids_all(public_vm_ips, services_to_stress)

    print_ip_to_container_id(services_to_stress, dictionary_ip_cont)
    #start_experiments(dictionary_ip_cont)

