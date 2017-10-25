'''
Automate Many experiments of Throttlebot
'''

import argparse
import traceback

from run_throttlebot import *

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--num_runs", help="Number of times to run the experiment")
    parser.add_argument("--config_file1", help="Configuration File for Throttlebot Execution")
    parser.add_argument("--resource_config", help='Default Resource Allocation for Throttlebot')
    args = parser.parse_args()

    conf_files = ['todo_config4.cfg', 'todo_config2.cfg', 'todo_config1.cfg']
    for conf_file in conf_files:
        for count in range(int(args.num_runs)):
            try:
                sys_config, workload_config, filter_config = parse_config_file(conf_file)
                mr_allocation = parse_resource_config_file(args.resource_config, sys_config)
                mr_allocation = filter_mr(mr_allocation,
                                          sys_config['stress_these_resources'],
                                          sys_config['stress_these_services'],
                                          sys_config['stress_these_machines'])
            
                run(sys_config, workload_config, filter_config, mr_allocation)
            except Exception, err:
                traceback.print_exc()
            
    print 'Completed!'

