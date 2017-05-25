import paramiko

def quilt_ssh(ip):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
	client.connect(ip, username="quilt")
        return client

def ssh_exec(ssh_client, cmd):
        _, _, stderr = ssh_client.exec_command(cmd)
	err = stderr.read()
        if err:
               	print ("Error execing {}: {}".format(cmd, err))
                
