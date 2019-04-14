from consolidate_services import *
from run_throttlebot import *

def run_placement(sys_config, mr_allocation, mr_ranking_list):
    instance_type = sys_config['machine_type']
    ffd_pack, imr_pack = ffd_pack(mr_allocation, instance_type, sort_by='CPU-QUOTA',
                                  imr_list=mr_ranking_list, round_up=False)
    print 'FFD pack is {}'.format(ffd_pack)
    print 'IMR pack is {}'.format(imr_pack)

# Run One iteration of Throttlebot to retrieve MR list
def run_one_iteration(sys_config, workload_config, filter_config, mr_allocation):
    sorted_mr_list = run(sys_config, workload_config, filter_config, mr_allocation, run_one_iteration=True)
    return sorted_mr_list

if __name__ == 'main':
    parser = argparse.ArgumentParser()
    parser.add_argument("--config_file")
    parser.add_argument("--resource_config")
    parser.add_argument("--impacted_mr_list")
    args = parser.parse_args()

    sys_config, workload_config, filter_config = parse_config_file(args.config_file)
    mr_allocation = parse_resource_config_file(args.resource_config, sys_config)

    sorted_mr_list = args.impacted_mr_list.split(',')
    if len(sorted_mr_list) == 0:
        sorted_mr_list = run_one_iteration(sys_config, workload_config, filter_config, mr_allocation)

    

