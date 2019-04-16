from consolidate_services import *
from run_throttlebot import *
import copy

def run_placement(sys_config, mr_allocation, mr_ranking_list):
    instance_type = sys_config['machine_type']
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


    num_imrs = 1
    num_imr_list = mr_ranking_list[:num_imrs]
    combine_resources(mr_allocation, num_imr_list, instance_type='m4.large', resource_type='CPU-QUOTA')

    

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

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config_file")
    parser.add_argument("--resource_config")
    parser.add_argument("--impacted_mr_list")
    args = parser.parse_args()
    
    sys_config, workload_config, filter_config = parse_config_file(args.config_file)
    mr_allocation = parse_resource_config_file(args.resource_config, sys_config)

    sorted_mr_list = parse_imr_rankings(args.impacted_mr_list)
    if len(sorted_mr_list) == 0:
        sorted_mr_list = run_one_iteration(sys_config, workload_config, filter_config, mr_allocation)

    run_placement(sys_config, mr_allocation, sorted_mr_list)

    

