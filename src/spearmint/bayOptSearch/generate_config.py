import json
from instance_specs import *

instance_type = 'm4.large'
resource_capacity = get_instance_specs(instance_type)

services = ['worker', 'master']
resources = ['CPU-QUOTA', 'DISK', 'NET', 'MEMORY']

overall_config = {}
overall_config['language'] = 'PYTHON'
overall_config['main-file'] = 'bayOpt.py'
overall_config['experiment-name'] = 'spark-bcd'
overall_config['likelihood'] = 'NOISELESS'
overall_config['variables'] = {}

resource_configuration = {}

for service in services:
    for resource in resources:
        variable_name = service + '-' + resource
        variable_config = {}
        variable_config['type'] = 'FLOAT'
        variable_config['size'] = 1
        variable_config['min'] = 
        variable_config['max'] = resource_capacity[resource]
        resource_configuration[variable_name] = variable_config

overall_config['variables'] = resource_configuration

with open('config.json', 'w') as fp:
    json.dump(overall_config, fp)
