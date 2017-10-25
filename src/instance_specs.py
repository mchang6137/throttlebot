import subprocess
import remote_execution as remote_exec

# Get the minimum of the resource allocations
# These are intended to be general to the architecture and assumes usage of cgroups
def get_instance_min_specs():
    resource_capacity = {'CPU-CORE': 0, 'DISK': 0, 'NET': 0, 'QPU-QUOTA': 0, 'MEMORY': 0}
    return resource_capacity

# Given a machine type, identify the amount of resource on the machine
# Assumes that the entire cluster has the same machine type
# All Resources that could be stressed must have an entry in here
# Return: Resource_type -> Maximum capacity {CPU-CORE: # of cores, DISK: I/O time in MBps, NET: bandwidth in Mbps}
def get_instance_specs(machine_type, provider='aws-ec2'):
    resource_capacity = {
        't1.nano':     {'CPU-CORE': 1,  'DISK': 0,   'NET': 0},
        't2.micro':    {'CPU-CORE': 1,  'DISK': 0,   'NET': 0},
        't2.small':    {'CPU-CORE': 1,  'DISK': 0,   'NET': 0},
        't2.medium':   {'CPU-CORE': 2,  'DISK': 0,   'NET': 0},
        't2.large':    {'CPU-CORE': 2,  'DISK': 0,   'NET': 0},
        't2.xlarge':   {'CPU-CORE': 4,  'DISK': 0,   'NET': 0},
        't2.2xlarge':  {'CPU-CORE': 8,  'DISK': 0,   'NET': 0},
        'm1.small':    {'CPU-CORE': 1,  'DISK': 0,   'NET': 0},
        'm1.medium':   {'CPU-CORE': 1,  'DISK': 0,   'NET': 0},
        'm1.large':    {'CPU-CORE': 2,  'DISK': 0,   'NET': 0},
        'm1.xlarge':   {'CPU-CORE': 4,  'DISK': 0,   'NET': 0},
        'm2.xlarge':   {'CPU-CORE': 2,  'DISK': 0,   'NET': 0},
        'm2.2xlarge':  {'CPU-CORE': 4,  'DISK': 0,   'NET': 0},
        'm2.4xlarge':  {'CPU-CORE': 8,  'DISK': 0,   'NET': 0},
        'm3.medium':   {'CPU-CORE': 1,  'DISK': 0,   'NET': 0,    'MEMORY': 3.75, 'STORAGE': '1 x 4 SSD'},
        'm3.large':    {'CPU-CORE': 1,  'DISK': 0,   'NET': 0,    'MEMORY': 7.5,  'STORAGE': '1 x 32 SSD'},
        'm3.xlarge':   {'CPU-CORE': 2,  'DISK': 0,   'NET': 0,    'MEMORY': 15,   'STORAGE': '2 x 40 SSD'},
        'm3.2xlarge':  {'CPU-CORE': 4,  'DISK': 0,   'NET': 0,    'MEMORY': 30,   'STORAGE': '2 x 40 SSD'},
        'm4.large':    {'CPU-CORE': 2,  'DISK': 71,  'NET': 450,  'MEMORY': 8000000000,    'STORAGE': 'ebsonly'},
        'm4.xlarge':   {'CPU-CORE': 4,  'DISK': 119, 'NET': 750,  'MEMORY': 16,   'STORAGE': 'ebsonly'},
        'm4.2xlarge':  {'CPU-CORE': 8,  'DISK': 159, 'NET': 1000, 'MEMORY': 34359738368,   'STORAGE': 'ebsonly'},
        'm4.4xlarge':  {'CPU-CORE': 16, 'DISK': 174, 'NET': 2000, 'MEMORY': 64,   'STORAGE': 'ebsonly'},
        'm4.10xlarge': {'CPU-CORE': 40, 'DISK': 174, 'NET': 4000, 'MEMORY': 160,  'STORAGE': 'ebsonly'},
        'm4.16xlarge': {'CPU-CORE': 64, 'DISK': 174, 'NET': 4700, 'MEMORY': 256,  'STORAGE': 'ebsonly'},
        'c1.medium':   {'CPU-CORE': 2,  'DISK': 0,   'NET': 0},
        'c1.xlarge':   {'CPU-CORE': 8,  'DISK': 0,   'NET': 0},
        'cc2.8xlarge': {'CPU-CORE': 16, 'DISK': 0,   'NET': 0},
        'cg1.4xlarge': {'CPU-CORE': 8,  'DISK': 0,   'NET': 0}, 
        'cr1.8xlarge': {'CPU-CORE': 16, 'DISK': 0,   'NET': 0},
        'c3.large':    {'CPU-CORE': 1,  'DISK': 0,   'NET': 0,    'MEMORY': 3.75, 'STORAGE': '2 x 16 SSD'},
        'c3.xlarge':   {'CPU-CORE': 2,  'DISK': 0,   'NET': 0,    'MEMORY': 7.5,  'STORAGE': '2 x 40 SSD'},
        'c3.2xlarge':  {'CPU-CORE': 4,  'DISK': 0,   'NET': 0,    'MEMORY': 15,   'STORAGE': '2 x 80 SSD'},
        'c3.4xlarge':  {'CPU-CORE': 8,  'DISK': 0,   'NET': 0,    'MEMORY': 30,   'STORAGE': '2 x 160 SSD'},
        'c3.8xlarge':  {'CPU-CORE': 16, 'DISK': 0,   'NET': 0,    'MEMORY': 60,   'STORAGE': '2 x 320 SSD'},
        'c4.large':    {'CPU-CORE': 2,  'DISK': 80,  'NET': 500,  'MEMORY': 3750000000, 'STORAGE': 'ebsonly'},
        'c4.xlarge':   {'CPU-CORE': 4,  'DISK': 119, 'NET': 1500,  'MEMORY': 7.5,  'STORAGE': 'ebsonly'},
        'c4.2xlarge':  {'CPU-CORE': 8,  'DISK': 158, 'NET': 1500, 'MEMORY': 15,   'STORAGE': 'ebsonly'},
        'c4.4xlarge':  {'CPU-CORE': 16, 'DISK': 174, 'NET': 2000, 'MEMORY': 30,   'STORAGE': 'ebsonly'},
        'c4.8xlarge':  {'CPU-CORE': 36, 'DISK': 174, 'NET': 4000, 'MEMORY': 60,   'STORAGE': 'ebsonly'},
        'hi1.4xlarge': {'CPU-CORE': 8,  'DISK': 0,   'NET': 0},
        'hs1.8xlarge': {'CPU-CORE': 8,  'DISK': 0,   'NET': 0},
        'g3.4xlarge':  {'CPU-CORE': 8,  'DISK': 0,   'NET': 0},
        'g3.8xlarge':  {'CPU-CORE': 16, 'DISK': 0,   'NET': 0},
        'g3.16xlarge': {'CPU-CORE': 32, 'DISK': 0,   'NET': 0},
        'g2.2xlarge':  {'CPU-CORE': 16, 'DISK': 0,   'NET': 0},
        'x1.16xlarge': {'CPU-CORE': 32, 'DISK': 0,   'NET': 0},
        'x1.32xlarge': {'CPU-CORE': 64, 'DISK': 0,   'NET': 0},
        'r4.large':    {'CPU-CORE': 1,  'DISK': 0,   'NET': 0},
        'r4.xlarge':   {'CPU-CORE': 2 , 'DISK': 0,   'NET': 0},
        'r4.2xlarge':  {'CPU-CORE': 4,  'DISK': 0,   'NET': 0},
        'r4.4xlarge':  {'CPU-CORE': 8,  'DISK': 0,   'NET': 0},
        'r4.8xlarge':  {'CPU-CORE': 16, 'DISK': 0,   'NET': 0},
        'r4.16xlarge': {'CPU-CORE': 32, 'DISK': 0,   'NET': 0},
        'r3.large':    {'CPU-CORE': 1,  'DISK': 0,   'NET': 0,    'MEMORY': 15,   'STORAGE': '1 x 32 SSD'},
        'r3.xlarge':   {'CPU-CORE': 2,  'DISK': 0,   'NET': 0,    'MEMORY': 30.5, 'STORAGE': '1 x 80 SSD'},
        'r3.2xlarge':  {'CPU-CORE': 4,  'DISK': 0,   'NET': 0,    'MEMORY': 61,   'STORAGE': '1 x 160 SSD'},
        'r3.4xlarge':  {'CPU-CORE': 8,  'DISK': 0,   'NET': 0,    'MEMORY': 122,  'STORAGE': '1 x 320 SSD'},
        'r3.8xlarge':  {'CPU-CORE': 16, 'DISK': 0,   'NET': 0,    'MEMORY': 244,  'STORAGE': '2 x 320 SSD'},
        'p2.xlarge':   {'CPU-CORE': 2,  'DISK': 0,   'NET': 0},
        'p2.8xlarge':  {'CPU-CORE': 16, 'DISK': 0,   'NET': 0},
        'p2.16xlarge': {'CPU-CORE': 32, 'DISK': 0,   'NET': 0},
        'i3.large':    {'CPU-CORE': 1,  'DISK': 0,   'NET': 0},
        'i3.xlarge':   {'CPU-CORE': 2,  'DISK': 0,   'NET': 0},
        'i3.2xlarge':  {'CPU-CORE': 4,  'DISK': 0,   'NET': 0},
        'i3.4xlarge':  {'CPU-CORE': 8,  'DISK': 0,   'NET': 0},
        'i3.8xlarge':  {'CPU-CORE': 16, 'DISK': 0,   'NET': 0},
        'i3.16xlarge': {'CPU-CORE': 32, 'DISK': 0,   'NET': 0},
        'i2.xlarge':   {'CPU-CORE': 2,  'DISK': 0,   'NET': 0,    'MEMORY': 4,  'STORAGE': '1 x 800 SSD'},
        'i2.2xlarge':  {'CPU-CORE': 4,  'DISK': 0,   'NET': 0,    'MEMORY': 8,  'STORAGE': '2 x 800 SSD'},
        'i2.4xlarge':  {'CPU-CORE': 8,  'DISK': 0,   'NET': 0,    'MEMORY': 16, 'STORAGE': '4 x 800'},
        'i2.8xlarge':  {'CPU-CORE': 16, 'DISK': 0,   'NET': 0,    'MEMORY': 32, 'STORAGE': '2 x 800 SSD'},
        'd2.xlarge':   {'CPU-CORE': 2,  'DISK': 0,   'NET': 0,    'MEMORY': 4,  'STORAGE': '3 x 2000 HDD'},
        'd2.2xlarge':  {'CPU-CORE': 4,  'DISK': 0,   'NET': 0,    'MEMORY': 8,  'STORAGE': '6 x 2000 HDD'},
        'd2.4xlarge':  {'CPU-CORE': 8,  'DISK': 0,   'NET': 0,    'MEMORY': 16, 'STORAGE': '12 x 2000 HDD'},
        'd2.8xlarge':  {'CPU-CORE': 18, 'DISK': 0,   'NET': 0,    'MEMORY': 36, 'STORAGE': '24 x 2000 HDD'}
    }

    # Some hacks to clean up the results returned by this function
    # Primarily, Storage is not a necessary field
    if 'STORAGE' in resource_capacity[machine_type]:
        del resource_capacity[machine_type]['STORAGE']
    resource_capacity[machine_type]['NET'] *= 1024
    resource_capacity[machine_type]['DISK'] *= 1048576
    resource_capacity[machine_type]['CPU-QUOTA'] = 100 * resource_capacity[machine_type]['CPU-CORE']
    return resource_capacity[machine_type]

