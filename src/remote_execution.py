import paramiko

def get_client(ip):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(ip, username="quilt", password="")
    return client

def ssh_exec(ssh_client, cmd, contains_container_id=False):
    _, _, stderr = ssh_client.exec_command(cmd)
    err = stderr.read()
    if err:
        print "Command contains container_id: {}".format(contains_container_id)
        print ("Error execing {}: {}".format(cmd, err))
        # Bug: only error upon container change error.
        if contains_container_id:
            raise SystemError('Container ID error for mr')

def close_client(ssh_client):
    ssh_client.close()
