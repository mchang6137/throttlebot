import paramiko

def get_client(ip):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(ip, username="quilt", password="")
    return client

def ssh_exec(ssh_client, cmd):
    _, _, stderr = ssh_client.exec_command(cmd)
    err = stderr.read()
    if err:
        print ("Error execing {}: {}".format(cmd, err))

def close_client(ssh_client):
    ssh_client.close()
