'''
Microservice Resource class
'''

class MR:
    def __init__(self, service_name, resource, instances):
        self.service_name = service_name
        self.resource = resource
        # instances should be a list of tuples: (vm_ip, container_id)
        self.instances = instances

    def to_string(self):
        return '{},{}'.format(self.service_name, self.resource)

    def to_string_csv(self):
        return '{}-{}'.format(self.service_name, self.resource)

    def __hash__(self):
        return hash((self.service_name, self.resource))

    def __eq__(self, other):
        return (self.service_name, self.resource) == (other.service_name, other.resource)
