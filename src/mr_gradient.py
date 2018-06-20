'''
Determines how to set the MR provisions for the gradient step
Involves parsing the gradient_mode of the sys_config

'''

from weighting_conversions import *
from mr import MR
import redis_resource as resource_datastore

''' 
Determines the resources to stress in order to predict the impact
of increasing a single MR (Otherwise known as the gradient step)

mr_candidates is a zero
Returns the a list of MRs and their new allocations
'''

def calculate_mr_gradient_schedule(redis_db, mr_candidates, sys_config, stress_weight):
    gradient_mode = sys_config['gradient_mode']
    if gradient_mode == 'single':
        return schedule_single_gradient(redis_db, mr_candidates, stress_weight)
    elif gradient_mode == 'inverted':
        return schedule_inverted_gradient(redis_db, mr_candidates, stress_weight)
    else:
        print 'Invalid Gradient Mode. Exiting...'
        exit()

def revert_mr_gradient_schedule(redis_db, mr_candidates, sys_config, stress_weight):
    gradient_mode = sys_config['gradient_mode']
    if gradient_mode == 'single':
        return revert_single_gradient(redis_db, mr_candidates, stress_weight)
    elif gradient_mode == 'inverted':
        return revert_inverted_gradient(redis_db, mr_candidates, stress_weight)
    else:
        print 'Invalid gradient mode. Exiting...'
        exit()
'''
Provisions resources for the analytic baseline
'''
def prepare_analytic_baseline(redis_db, sys_config, stress_weight):
    gradient_mode = sys_config['gradient_mode']
    if gradient_mode == 'single':
        # Single requires no special preparation of the resources
        return {}
    elif gradient_mode == 'inverted':
        return prepare_inverted_baseline(redis_db, stress_weight)
    else:
        print 'Invalid Gradient Mode. Exiting...'
        exit()

'''
Reverts the resource provisions for the analytic baseline
(prepare_analytic_baseline does not use this so we do)
'''
def revert_analytic_baseline(redis_db, sys_config):
    gradient_mode = sys_config['gradient_mode']
    if gradient_mode == 'single':
        return {}
    elif gradient_mode == 'inverted':
        return revert_inverted_baseline(redis_db)
    else:
        print 'Invalid gradient mode. Exiting...'
        exit()
        
# Prepares an all resource stress as the baseline
def prepare_inverted_baseline(redis_db, stress_weight):
    mr_to_alloc = {}
    all_mr_list = resource_datastore.get_all_mrs(redis_db)
    for mr in all_mr_list:
        current_mr_alloc = resource_datastore.read_mr_alloc(redis_db, mr)
        new_alloc = convert_percent_to_raw(mr, current_mr_alloc, stress_weight)
        mr_to_alloc[mr] = new_alloc
    return mr_to_alloc

# Reverts the changes in resource preparation
# Leverages the fact that the original changes were not written to Redis
def revert_inverted_baseline(redis_db):
    mr_to_alloc = {}
    all_mr_list = resource_datastore.get_all_mrs(redis_db)
    for mr in all_mr_list:
        current_mr_alloc = resource_datastore.read_mr_alloc(redis_db, mr)
        new_alloc = convert_percent_to_raw(mr, current_mr_alloc, 0)
        mr_to_alloc[mr] = new_alloc
    return mr_to_alloc
    
# Only schedule a single resource
def schedule_single_gradient(redis_db, mr_candidates, stress_weight):
    mr_to_alloc = {}
    for mr_candidate in mr_candidates:
        current_mr_alloc = resource_datastore.read_mr_alloc(redis_db, mr_candidate)
        new_alloc = convert_percent_to_raw(mr_candidate, current_mr_alloc, stress_weight)
        mr_to_alloc[mr_candidate] = new_alloc
    return mr_to_alloc

def revert_single_gradient(redis_db, mr_candidates, stress_weight):
    mr_to_alloc = {}
    for mr_candidate in mr_candidates:
        original_mr_alloc = resource_datastore.read_mr_alloc(redis_db, mr_candidate)
        mr_to_alloc[mr_candidate] = original_mr_alloc
    return mr_to_alloc
        
# Assumes the baseline stressing of other resources are already in place
def schedule_inverted_gradient(redis_db, mr_candidates, stress_weight):
    mr_to_alloc = {}
    for mr in mr_candidates:
        # Simulate ADDING a resource by reverting it to its original, non-stressed amount
        # This is the amount recorded in Redis
        current_mr_alloc = resource_datastore.read_mr_alloc(redis_db, mr)
        mr_to_alloc[mr] = current_mr_alloc
    return mr_to_alloc

# Reverts the added resource to the remaining resources
def revert_inverted_gradient(redis_db, mr_candidates, stress_weight):
    mr_to_alloc = {}
    for mr in mr_candidates:
        original_alloc = resource_datastore.read_mr_alloc(redis_db, mr)
        new_alloc = convert_percent_to_raw(mr, original_alloc, stress_weight)
        mr_to_alloc[mr] = new_alloc
    return mr_to_alloc
