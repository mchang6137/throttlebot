'''
Automate Many experiments of Throttlebot
'''

import argparse
import traceback

from run_clampdown import *

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--num_runs", help="Number of times to run the experiment")
    parser.add_argument("--config_file", help="Configuration File for Throttlebot Execution")
    parser.add_argument("--resource_config", help='Default Resource Allocation for Throttlebot')
    args = parser.parse_args()

    trial_to_overhead = {}
    for count in range(int(args.num_runs)):
        try:
            sys_config, workload_config, filter_config = parse_clampdown_config_file(args.config_file)
            mr_allocation = parse_resource_config_file(args.resource_config, sys_config)
            mr_allocation = filter_mr(mr_allocation,
                                      sys_config['stress_these_resources'],
                                      sys_config['stress_these_services'],
                                      sys_config['stress_these_machines'])

            experiment_start = time.time()
            experiment_iteration = runClampdown(sys_config, workload_config, filter_config, mr_allocation)
            experiment_end = time.time()
            runtime = experiment_end - experiment_start
            trial_to_overhead[count] = (experiment_iteration, runtime)
            print 'Trial overhead is {}'.format(trial_to_overhead)
        except Exception, err:
            traceback.print_exc()

    print 'Completed!'
    print trial_to_overhead

# (5,436 sec)
# {0: (6, 486.6667308807373), 1: (4, 345.2677080631256), 2: (5, 493.66548919677734), 3: (13, 1544.4055361747742), 4: (4, 332.8213529586792), 5: (7, 621.3301801681519)}
# Trial overhead is {0: (4, 578.1906540393829), 3: (6, 802.8485651016235), 4: (4, 572.9136738777161)}
# Trial overhead is {0: (12, 1881.8307039737701), 1: (4, 584.6465392112732), 2: (12, 2493.1996941566467), 3: (5, 804.1368129253387), 4: (5, 664.010171175003)}

#{0: (12, 1881.8307039737701), 1: (4, 584.6465392112732), 2: (12, 2493.1996941566467), 3: (5, 804.1368129253387), 4: (5, 664.010171175003), 6: (6, 856.1476581096649), 7: (4, 519.7894358634949), 8: (4, 444.07016491889954), 9: (4, 621.9613389968872), 10: (3, 380.3911108970642), 13: (5, 724.5969071388245), 14: (9, 1204.6040868759155), 15: (5, 726.7741861343384), 16: (5, 607.3500599861145)}
# {0: (5, 410.8586778640747), 1: (None, 1545.6361060142517), 2: (4, 375.37031292915344), 3: (6, 582.8989629745483), 4: (5, 504.99704813957214), 5: (10, 988.8418288230896), 6: (14, 1409.2385971546173), 7: (5, 474.04735493659973), 8: (5, 405.5897469520569), 9: (7, 683.8803508281708), 10: (7, 737.8998699188232), 11: (5, 523.9921967983246), 12: (7, 609.4941959381104), 13: (9, 990.6847410202026), 14: (6, 572.2378859519958), 15: (6, 513.3694109916687), 16: (2, 190.54992294311523), 17: (5, 429.50618386268616), 18: (5, 496.03349709510803), 19: (5, 440.4174609184265)}~
