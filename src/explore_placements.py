from consolidate_services import *
from run_throttlebot import *
from instance_specs import *
import copy

def run_placement(sys_config, mr_allocation, mr_ranking_list):
    instance_type = sys_config['machine_type']
    '''
    ffd_packing, imr_packing = ffd_pack(mr_allocation, instance_type, sort_by='CPU-QUOTA',
                                  imr_list=mr_ranking_list, round_up=False)
    print 'FFD pack is {}'.format(ffd_packing)
    print 'IMR pack is {}'.format(imr_packing)

    rounded_imrs = 1
    rounded_mr_allocation = copy.deepcopy(mr_allocation)
    for rank in range(rounded_imrs):
        mr_subject = mr_ranking_list[rank]
        rounded_mr_allocation[mr_subject] = roundup(mr_allocation[mr_subject])
    ffd_packing_rounded, imr_packing_rounded = ffd_pack(rounded_mr_allocation, instance_type, sort_by='CPU-QUOTA',
                                                        imr_list=mr_ranking_list, round_up=False)
    print 'FFD packing, first {} rounded is {}'.format(rounded_imrs, ffd_packing_rounded)
    print 'IMR packing, first {} roudned is {}'.format(rounded_imrs, imr_packing_rounded)

    '''
    num_imrs = 1
    num_imr_list = mr_ranking_list[:num_imrs]
    deploy_together = combine_resources(mr_allocation, num_imr_list,
                                        instance_type='m4.large', resource_type='CPU-QUOTA')

    ffd_pack_affinity, imr_pack_affinity = ffd_pack(mr_allocation, instance_type,
                                                    sort_by='CPU-QUOTA', imr_list=mr_ranking_list,
                                                    round_up=False, deploy_together=deploy_together)

    print 'FFD packing with affinity, first {} rounded is {}'.format(num_imrs, ffd_packing_affinity)
    print 'IMR packing with affinity, first {} roudned is {}'.format(num_imrs, imr_packing_affinity)

def assign_cores(sys_config, mr_allocation, mr_ranking_list):
    instance_type = sys_config['machine_type']
    available_cores = get_instance_specs(instance_type)['CPU-CORE']
    
    num_imrs = 1
    num_imr_list = mr_ranking_list[:num_imrs]
    deploy_together = combine_resources(mr_allocation, num_imr_list,
                                        instance_type='m4.large', resource_type='CPU-QUOTA')

    vm_list = get_actual_vms()
    vm_to_service = get_vm_to_service(vm_list)
    service_to_container_info = get_service_placements(vm_list)
    print service_to_container_info.keys()

    vm_to_cores_pinned = {}
    for vm in vm_list:
        vm_to_cores_pinned[vm] = 0

    # Every container must be pinned to some core
    instance_pinned = {}
    for service in service_to_container_info:
        print 'In instance pinned, service is {}'.format(service)
        for instance in service_to_container_info[service]:
            key = instance[0] + '&' + instance[1]
            instance_pinned[key] = False

    for mr_set in deploy_together:
        print mr_set
        num_containers = len(mr_set)
        vm_pin = None
        for vm in vm_to_service:
            matches = 0
            for mr in mr_set:
                if mr.service_name in vm_to_service[vm]:
                    matches += 1
            if matches == num_containers:
                vm_pin = vm
                # Remove from vm_to_service so we don't schedule same service twice.
                for mr in mr_set:
                    vm_to_service[vm].remove(mr.service_name)
                break
        if vm_pin:
            total_cpu_alloc = 0
            for mr in mr_set:
                total_cpu_alloc += mr_allocation[mr]
            num_cores = int(roundup(total_cpu_alloc) / 100) - 1
            pin_cores = (vm_to_cores_pinned[vm], vm_to_cores_pinned[vm] + num_cores)
            vm_to_cores_pinned[vm] += num_cores

            for mr in mr_set:
                ssh_client = get_client(vm_pin)
                service_instances = service_to_container_info[mr.service_name]
                container_id = ''
                for inst in service_instances:
                   if inst[0] == vm_pin:
                        container_id = inst[1]
                assert container_id != ''
                set_cpu_cores(ssh_client, container_id, pin_cores)
                instance_pinned[vm_pin + '&' + container_id] = True

    # Handle remaining non-affinity based containers
    for service in service_to_container_info:
        for instance in service_to_container_info[service]:
            vm_ip = instance[0]
            container_id = instance[1]
            pin_key = vm_ip + '&' + container_id
            if instance_pinned[pin_key] is True:
                continue
            lowest_core_index = vm_to_cores_pinned[vm]
            pin_cores = (lowest_core_index, available_cores - 1)
            ssh_client = get_client(vm_ip)
            set_cpu_cores(ssh_client, container_id, pin_cores)
            instance_pinned[pin_key] = True

    print instance_pinned
    print 'Done'
            

# Run One iteration of Throttlebot to retrieve MR list
def run_one_iteration(sys_config, workload_config, filter_config, mr_allocation):
    sorted_mr_list = run(sys_config, workload_config, filter_config, mr_allocation, run_one_iteration=True)
    return sorted_mr_list

# Ordered list of IMRs [[MR, perf]]
def parse_imr_rankings(imr_ranking_csv):
    ranked_mr_list = []
    with open(imr_ranking_csv, 'rb') as imr_ranking:
        reader = csv.DictReader(imr_ranking)

        for row in reader:
            service_name = row['SERVICE']
            resource = row['RESOURCE']
            perf = row['PERF']

            mr = MR(service_name, resource, None)
            ranked_mr_list.append(mr)
            
    return ranked_mr_list

# Automatically generate placements
def generate_placements(placement_count):
    service_placement = {} # Paste placement here
    disk_base = 10
    service_to_quilt_spec = {'node-app:node-todo.git': 'mean.app',
                             'quilt/mongo': 'mean.mongo',
                             'haproxy:1.7': 'mean.proxy'}

    times_seen = {}
    for service in service_to_quilt_spec:
        times_seen[service] = 0

    for node in service_placement.keys():
        for service_name in service_placement[node]:
            quilt_var = service_to_quilt_spec[service_name]
            print '{}.cluster[{}].placeOn({{diskSize: {}}});'.format(quilt_var,
                                                                       times_seen[service_name],
                                                                       disk_base)
            times_seen[service_name] += 1
            
        disk_base += 1
        
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config_file")
    parser.add_argument("--resource_config")
    parser.add_argument("--impacted_mr_list")
    parser.add_argument("--assign_cores")
    args = parser.parse_args()
    
    sys_config, workload_config, filter_config = parse_config_file(args.config_file)
    mr_allocation = parse_resource_config_file(args.resource_config, sys_config)

    sorted_mr_list = parse_imr_rankings(args.impacted_mr_list)
    if len(sorted_mr_list) == 0:
        sorted_mr_list = run_one_iteration(sys_config, workload_config, filter_config, mr_allocation)

    if args.assign_cores == 'yes':
        assign_cores(sys_config, mr_allocation, sorted_mr_list)
    else:
        run_placement(sys_config, mr_allocation, sorted_mr_list)

    

