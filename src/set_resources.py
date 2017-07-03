import socket
from modify_resources import *
from remote_execution import *


"""
TEMPLATE FOR SCRIPT:
Start by declaring the IP by 'IP,<ip_address>'
Then declare the container id by 'Container,<container_id'
Then set the desired resources:
    CPU Throttling (single core) 'CPU,<cpu_percentage>' (1 to 100, 100 being MAX CPU)
    CPU Core pinning 'CPUC,<num_cores>' Note: Core pinning will override cpu throttling
    DISK read/write rates (bps) 'DISK,<disk_bps>'
    NETWORK speeds (bps) 'NET,<net_bps>'
    *** To reset any of the above resources, set the value to 0
Continue to declare IP, Containers, and Resources
**Note: This script is read sequentially, so a container_id will be associated with
    the most recent declared IP. The same goes with container resources.
When finished, you must add 'END' to the end.


Example Script:

IP,54.219.160.163
Container,127378c5361b
CPU,90
NET,10000000
Container,8a4b95ab82b8
CPUC,0
NET,10000000
IP,54.183.240.129
Container,14abb2058a70
CPUC,0
NET,10000000
IP,54.153.81.158
Container,82e4fb0d679a
CPUC,0
NET,10000000
END
"""


def error_message(index, e_type):
    if e_type == 'gen':
        print "Error on line {}. Either a comma error, emptyline, or missing END.".format(index)
    elif e_type == 'ip':
        print "Error on line {}. IP is not valid.".format(index)
    elif e_type == 'value':
        print "Error on line {}. Resource values must be integers.".format(index)
    elif e_type == 'cpu':
        print "Error on line {}. CPU values must be between 0 and 100. (100 as MAX CPU)".format(index)
    elif e_type == 'dep':
        print "Error on line {}. IP and container_ids must be stated before setting resources.".format(index)
    elif e_type == 'unk':
        print "Error on line {}. Uknown command.".format(index)
    print "Exiting script"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("file_name", help="Name of file that contains container resource values")
    args = parser.parse_args()

    with open(args.file_name) as config:
        ssh_clients = {}
        ssh_client = None
        container_id = None
        line_numb = 1
        for line in config:
            words = line.strip().split(',')
            if len(words) == 1:
                if words[0] == 'END':
                    break;
                else:
                    error_message(line_numb, 'gen')
                    exit()
            elif len(words) == 2:
                ID = words[0]
                if ID == 'IP':
                    ip_address = words[1]
                    try:
                        socket.inet_aton(ip_address)
                    except:
                        error_message(line_numb, 'ip')
                        exit()
                    if ip_address not in ssh_clients:
                        ssh_clients[ip_address] = get_client(ip_address)
                    ssh_client = ssh_clients[ip_address]
                    print 'Now setting IP {}\'s resources'.format(ip_address)
                elif ID == 'Container':
                    container_id = words[1]
                    print 'Now setting container {}\'s resources'.format(container_id)
                elif ID == 'CPU' or ID == 'CPUC' or ID == 'DISK' or ID == 'NET':
                    if ssh_client and container_id:
                        if ID == 'CPU':
                            try:
                                cpu_value = int(words[1])
                                if cpu_value > 100 or cpu_value < 0:
                                    raise ValueError('')
                            except:
                                error_message(line_numb, 'cpu')
                                exit()
                            if cpu_value == 0:
                                reset_cpu_quota(ssh_client, container_id)
                            else:
                                set_cpu_quota(ssh_client, container_id, 1000000, cpu_value * 1000000 / 100)
                        elif ID == 'CPUC':
                            try:
                                cpu_cores = int(words[1])
                            except:
                                error_message(line_numb, 'value')
                                exit()
                            if cpu_cores == 0:
                                reset_cpu_cores(ssh_client, container_id)
                            else:
                                core_cmd = '0-{}'.format(cpu_cores - 1)
                                set_cpu_cores(ssh_client, container_id, core_cmd)
                        elif ID == 'DISK':
                            try:
                                disk_bps = int(words[1])
                            except:
                                error_message(line_numb, 'value')
                                exit()
                            change_container_blkio(ssh_client, container_id, disk_bps)
                        else:
                            try:
                                net_bps = int(words[1])
                            except:
                                error_message(line_numb, 'value')
                                exit()
                            if net_bps == 0:
                                reset_egress_network_bandwidth(ssh_client, container_id)
                            else:
                                try:
                                    set_egress_network_bandwidth(ssh_client, container_id, {container_id:net_bps})
                                except:
                                    print 'Warning: Container {}\'s network cannot be set'.format(container_id)
                    else:
                        error_message(line_numb, 'dep')
                        exit()
                else:
                    error_message(line_numb, 'unk')
                    exit()
            else:
                error_message(line_numb, 'gen')
                exit()
            line_numb += 1
        print "Container resources were applied."
        exit()
