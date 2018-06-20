import paramiko

def get_client(ip):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(ip, username="quilt", password="")
    return client

def ssh_exec(ssh_client, cmd, contains_container_id=False, return_error=False):
    _,stdout,stderr = ssh_client.exec_command(cmd)
    err = stderr.read()
    if err:
        print ("Error execing {}: {}".format(cmd, err))

        if contains_container_id:
            raise SystemError('Error caused by container ID')
    
    if return_error:
        return _,stdout,stderr

def close_client(ssh_client):
    ssh_client.close()
