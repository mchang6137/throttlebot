Instructions on how to use ThrottleBot:

1. Run stress_scheduler.py with python2.7 with the proper arguments.
The mandatory arguments and options needed for Throttlebot to run correctly are the website_ip, victim_machine_public_ip, experiement_type, services to stress, resources to stress, and stressing policy. If there are multiple website_ips, victim_ips, services, and resources, separate them with a single comma ','. The optional arguments will vary depending on your experiment type and preference. For example, if I wanted to run an experiment to benchmark the performance of all todo-app services under all levels of stress to all resources, I could run:

python2.7 stress_scheduler.py WEBSITE1,WEBSITE2,WEBSITE3 VICTIM1,VICTIM2,VICTIM3 todo-app --traffic_generator_public_ip=GENERATOR1 --stress_all_services --stress_all_resources --stress_search_policy='ALL'

where WEBSITE, VICTIM, and GENERATOR are the IPs for the websites, victim machines, and the traffic generator respectively.

Refer to the help section for more information.

2. If necessary, set the "password" variables for your SSH keys. Without this, Throttlebot cannot execute commands on the virtual machines. They are located within remote_execution.py and measure_performance_MEAN_py3.py.


## Deploying a Kubernetes cluster on AWS
These instructions will cover launching a Kubernetes cluster  on AWS and deploying a simple application on this cluster.

### Tools
This guide recommends the use of [Kubernetes Operations](https://github.com/kubernetes/kops) (kops) to deploy and maintain the cluster.

Alternatives:
- [kube-aws](https://github.com/kubernetes-incubator/kube-aws) - requires external DNS name
- kube-up - deprecated shell script for launching clusters, not compatible with kubernetes 1.6+

source: https://kubernetes.io/docs/getting-started-guides/aws/

### Prerequisites
- kubectl - Kubernetes command-line tool
- kops
- aws-cli

On macOS with Homebrew:
```
$ brew install kubectl
$ brew install kops
$ brew install awscli
```

### Configure AWS User Permissions
Using kops requires the correct API credentials for your AWS account (AmazonEC2FullAccess, AmazonRoute53FullAccess, AmazonS3FullAccess, IAMFullAccess, AmazonVPCFullAccess).

```
$ aws iam create-group --group-name kops

$ aws iam attach-group-policy --policy-arn arn:aws:iam::aws:policy/AmazonEC2FullAccess --group-name kops
$ aws iam attach-group-policy --policy-arn arn:aws:iam::aws:policy/AmazonRoute53FullAccess --group-name kops
$ aws iam attach-group-policy --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess --group-name kops
$ aws iam attach-group-policy --policy-arn arn:aws:iam::aws:policy/IAMFullAccess --group-name kops
$ aws iam attach-group-policy --policy-arn arn:aws:iam::aws:policy/AmazonVPCFullAccess --group-name kops

$ aws iam create-user --user-name kops
$ aws iam add-user-to-group --user-name kops --group-name kops
$ aws iam create-access-key --user-name kops
```
```
# set up the aws client to use the new IAM user
$ aws configure

# Export the variables for kops use
$ export AWS_ACCESS_KEY_ID=<access key>
$ export AWS_SECRET_ACCESS_KEY=<secret key>
```
source: https://github.com/kubernetes/kops/blob/master/docs/aws.md

### Set up cluster state storage
Create a S3 bucket to store all information regarding cluster configuration and state.
```
$ aws s3api create-bucket --bucket {bucket_name} --region {aws_region}
$ export KOPS_STATE_STORE=s3://{bucket_name}
```

### Launching a Kubernetes gossip-based cluster
Use the following command to launch your cluster.
```
$ kops create cluster {cluster_name}.k8s.local --zones {aws_zone} --yes
```
After a couple of minutes, you should be able to validate the cluster has been created.
```
$ kops validate cluster
```
You can delete your cluster using a simple command.
```
$ kops delete cluster {cluster_name}.k8s.local --yes
````
source: http://blog.arungupta.me/gossip-kubernetes-aws-kops/

### Deploying a simple multi-tier application on your cluster
The Kubernetes documentation covers how to launch a basic web application using PHP and Redis. The documentation also includes how to externalize the application.
https://kubernetes.io/docs/tutorials/stateless-application/guestbook/

Alternatively, one can pull the following repository and deploy the application with a single comand.
https://github.com/kubernetes/examples/tree/master/guestbook

First check that your cluster is configured properly.
```
$ kubectl cluster-info
```
The application can then be deployed with a single command.
```
$ kubectl create -f guestbook/all-in-one/guestbook-all-in-one.yaml
```
You can check your currently running services.
```
$ kubectl get services
```
You can also delete the application by running the following command.
```
$ kubectl delete -f guestbook/all-in-one/guestbook-all-in-one.yaml
```


## ThrottleBot Compatibility
The SSH public key for EC2 instances launched by kops defaults to ~/.ssh/id_rsa.pub.


### CPU
Did not run into major issues.

### Disk
Must change how to reference cgroups and individual containers in change_container_blkio() function in modify_resources.py.

Kubernetes organizes containers using pods so the path has to be changed to:
```
$ /sys/fs/cgroup/blkio/kubepods/burstable/{pod#}/{container_ID}*/blkio.throttle.read_bps_device
````

### Network

Approach (does not work): Identify the veth of individual containers and use tc with HTB queuing discipling to throttle network bandwidth.

Identify the veth of individual containers by running the following command from shell.
```
$ cat /sys/class/net/veth11d4238/ifindex
```
Set bandwidth using tc.
```
$ sudo tc qdisc add dev {veth#} handle 1: root htb default 11
$ sudo tc class add dev {veth#} parent 1: classid 1:1 htb rate 1kbps
$ sudo tc class add dev {veth#} parent 1:1 classid 1:11 htb rate 1kbps
``` 

Other approaches:
- Tried other queuing disciplines
- Create custom [Docker bridges](https://docs.docker.com)? (tricky/have to define bridge before container deployment)


