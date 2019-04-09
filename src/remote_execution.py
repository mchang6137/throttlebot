import paramiko
import logging

def get_client(ip):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print("Client is connecting")
    client.connect(ip, username="admin", password="")
    print("Client has connected")
    return client

def ssh_exec(ssh_client, cmd, modifies_container=False, return_error=False):
    _,stdout,stderr = ssh_client.exec_command(cmd)
    err = stderr.read()
    if err:
        logging.info("Error execing {}: {}".format(cmd, err))

        if modifies_container:
            raise SystemError('Error caused by container ID')
    
    if return_error:
        return _,stdout,stderr

def close_client(ssh_client):
    ssh_client.close()
