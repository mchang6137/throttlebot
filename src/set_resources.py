import csv
import socket
from modify_resources import *
from remote_execution import *


"""
Step 1:
First run script with --create option. This will create an empty formatted .csv file with your specified file name.

Step 2:
Fill each row to your specifications. Each row corresponds to one container residing in one machine.

KEY:
IP: Machine IP where container is located
Container: The container id that 'docker ps' generates
CPUC: The number of cpu-cores allocated to that machine (1 to <Number of CPUs available>) (0 to reset)
CPU: Percentage of available CPU allocated to that machine (1 - 100, 100 being the max) (0 to reset) (Multicore)
DISK: read/write rates (bps) (0 to reset)
NET: network speed (bps) (0 to reset)
"""


def generate_empty_file(name):
    output_file_name = '{}.csv'.format(name)
    with open(output_file_name, 'wb') as csvfile:
        fieldnames = ['IP', 'Container', 'CPUC', 'CPU', 'DISK', 'NET', 'MEMORY']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()


def error_message(index, e_type):
    if e_type == 'ip':
        print "Error on line {}. IP is not valid.".format(index)
    elif e_type == 'value':
        print "Error on line {}. Resource values must be integers.".format(index)
    elif e_type == 'cpu':
        print "Error on line {}. CPU values must be between 0 and 100. (100 as MAX CPU)".format(index)
    print "Exiting script"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("file_name", help="Name of file that contains container resource values")
    parser.add_argument("--create", action="store_true", help="Just creates empty formatted csv file")
    args = parser.parse_args()

    if args.create:
        generate_empty_file(args.file_name)
        exit()

    with open(args.file_name) as csvfile:
        ssh_clients = {}
        line_numb = 2
        reader = csv.DictReader(filter(lambda row: row[0] != '#', csvfile))
        for row in reader:
            ip_address = row['IP']
            container_id = row['Container']
            cpuc_value = row['CPUC']
            cpu_value = row['CPU']
            disk_value = row['DISK']
            net_value = row['NET']
            memory = row['MEMORY']

            try:
                socket.inet_aton(ip_address)
            except:
                error_message(line_numb, 'ip')
                exit()
            if ip_address not in ssh_clients:
                ssh_clients[ip_address] = get_client(ip_address)
            ssh_client = ssh_clients[ip_address]
            #
            # print 'Now setting {} {}\'s resources'.format(ip_address, container_id)
            #
            # Setting CPU Cores
            # try:
            #     cpu_cores = int(cpuc_value)
            # except:
            #     error_message(line_numb, 'value')
            #     exit()
            # if cpu_cores == 0:
            #     reset_cpu_cores(ssh_client, container_id)
            # else:
            #     set_cpu_cores(ssh_client, container_id, cpu_cores)

            # Setting CPU throttling
            try:
                cpu_percentage = int(cpu_value)
                if cpu_percentage > 100 or cpu_percentage < 0:
                    raise ValueError('')
            except:
                error_message(line_numb, 'cpu')
                exit()
            if cpu_percentage == 0:
                reset_cpu_quota(ssh_client, container_id)
            else:
                set_cpu_quota(ssh_client, container_id, 1000000, cpu_percentage)

            # Setting DISK speeds
            try:
                disk_bps = int(disk_value)
            except:
                error_message(line_numb, 'value')
                exit()
            set_container_blkio(ssh_client, container_id, disk_bps)

            # Setting network speeds
            try:
                net_bps = int(net_value)
            except:
                error_message(line_numb, 'value')
                exit()
            if net_bps == 0:
                try:
                    reset_egress_network_bandwidth(ssh_client, container_id)
                except:
                    print 'Warning: Container {}\'s network cannot be reset'.format(container_id)
            else:
                try:
                    set_egress_network_bandwidth(ssh_client, container_id, net_bps)
                except:
                    print 'Warning: Container {}\'s network cannot be set'.format(container_id)

            line_numb += 1

            # Setting Memory Allocation
            try:
                memory_b = int(memory)
            except:
                error_message(line_numb, 'value')
                exit()
            set_memory_size(ssh_client, container_id, memory_b)

        print "Container resources were applied."
        exit()
