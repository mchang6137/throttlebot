from remote_execution import *

#Returns potential interface names in the format of interfaces
def get_container_id(ssh_client, full_id=False, append_c=True):
    all_names = get_container_names(ssh_client)
    all_ids = []
    for name in all_names:
        cmd = 'docker inspect --format=\"{{{{.Id}}}}\" {}'.format(name)

        if full_id is False:
            #First 13 characters because of interface naming
            cmd += '| awk \'{{print substr($0,0,13)}}\''
        _, stdout, _ = ssh_client.exec_command(cmd)
        if append_c:
            all_ids.append(stdout.read()[:-1] + '_c')
        else:
            all_ids.append(stdout.read()[:-1])
    return all_ids

def get_container_names(ssh_client, only_running=True):
    names = get_container_info(ssh_client, 'name', only_running=True)
    if 'minion' in names:
        names.remove("minion")
    return names

def get_container_full_id(ssh_client, only_running=True):
    return get_container_info(ssh_client, 'container_id', only_running=True)

def get_container_info(ssh_client, command, only_running=True):
    options = " -a" if not only_running else ""
    if command == 'name':
        options += ' --format="{{.Names}}"'
    elif command == 'container_id':
        options += ' --format="{{.ID}}"'
    _, stdout, _ = ssh_client.exec_command('docker ps' + options)
    results = stdout.read().splitlines()
    return results

def get_container_veth(ssh_client, container_id):
    get_interface_cmd = "docker inspect {} | grep EndpointID".format(container_id)
    _,stdout,stderr = ssh_exec(ssh_client, get_interface_cmd, contains_container_id=True):
    lines = stdout.readlines()[1]
    interface_name = str(lines).split('\"')[3][:15]
    return interface_name
