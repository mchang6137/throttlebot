'''Converts various weightings between 0 and 100 to an actual amount to stress particular resource to'''
from modify_resources import *
from remote_execution import *

def weighting_to_latency(weighting):
    MAX_LATENCY = 2
    if weighting < 0 or weighting > 100:
        print ('Invalid Weighting')
        return
    return (weighting / 100.0) * MAX_LATENCY

###Possible substitute using network bandwidth throttling instead of latency values
###Returns the throttled bandwidth to bits/sec
def weighting_to_bandwidth(ssh_client, weighting, container_to_capacity):
    if weighting < 0 or weighting > 100:
        print 'Invalid Weighting'
        return

    #Convert to stress amount AND convert from Mbps to bps
    for container in container_to_capacity:
        reduction = 100 - weighting
        container_to_capacity[container] = container_to_capacity[container] * reduction / 100 * 1000000

    return container_to_capacity

def weighting_to_blkioweight(weighting):
    MAX_BLKIO = 990
    if weighting < 0 or weighting > 100:
        print ('Invalid Weighting')
        return
    #+10 because blkio only accepts values between 10 and 1000
        #Lower weighting must have lower bound on the blkio weight allocation
    return int((weighting / 100.0) * MAX_BLKIO + 10)

def weighting_to_disk_access_rate(weighting):
    #This is a hack! To find the max disk throughput, try:
    # sudo hdparm -t /dev/xvda
    #Units are Bytes/second
    #70 MB = 7000000 Bytes
    #INTRA-VM
    MAX_DISK_READ = 70000000

    reduced = 100 - weighting
    return int(MAX_DISK_READ * reduced / 100)

def weighting_to_cpu_quota(weighting):
    if weighting < 0 or weighting > 100:
        print ('Invalid Weighting')
        return
    reduced = 100 - weighting
    return int(1000000 * reduced / 100)

def weighting_to_cpu_period(weighting):
    weighting = float(100 - weighting)
    return weighting/100
