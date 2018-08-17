import csv, random, logging
from mr import MR
from run_throttlebot import fake_run, parse_resource_config_file, parse_config_file

tiers = {
    1: ["osalpekar/spark-image-compress..."],
    2: ["elasticsearch:2.4", "library/postgres:9.4", "tsaianson/node-apt-app", "haproxy:1.7", "hantaowang/logstash-postgres"],
    3: ["kibana:4", "mysql:5.6.32"],
}

resources = ["CPU-QUOTA", "DISK", "NET"]

def identify_tier_resources(mr_allocation):
    tier_resources = {}

    for mr, value in mr_allocation.items():
        assert mr.resource in resources
        for tier, lst in tiers.items():
            if mr.service_name in lst:
                tier_mr = MR(tier, mr.resource, [])
                if tier_mr in tier_resources:
                    assert tier_resources[tier_mr] == value
                else:
                    tier_resources[tier_mr] = value


    for resource in resources:
        total = 0
        for i in range(1, 4):
            total += tier_resources[MR(i, resource, [])]
        tier_resources[MR(0, resource, [])] = total

    return tier_resources

def scramble_tiers(tier_resources, times):
    def permute(a, l, r):
        if l==r:
            yield a
        else:
            for i in xrange(l,r+1):
                a[l], a[i] = a[i], a[l]
                for p in permute(a, l+1, r):
                    yield p
                a[l], a[i] = a[i], a[l]

    def generate_splits(total):
        splits = [1.0/6.0, 1.0/3.0, 1.0/2.0]
        orderings = []
        for permutation in permute(splits, 0, 2):
            orderings.append([total * x for x in permutation])
        return orderings
    
    splits = generate_splits(1)
    done = []
    t = 0
    while t < times:
        not_changed = random.choice(resources)
        key = []
        for r in resources:
            if r != not_changed:
                split = random.choice(splits)
                for i in range(1, 4):
                    tier_resources[MR(i, r, [])] = split[i - 1] * tier_resources[MR(0, r, [])]
                key.append((r, split, []))
        if key not in done:
            t += 1
            yield tier_resources.copy()

def tier_to_configuration(tier_resources):
    config = {}
    for i in range(1, 4):
        for r in resources:
            value = tier_resources[MR(i, r, [])]
            for service in tiers[i]:
                config[MR(service, r, [])] = value
    return config

# ------------------------------------------------------------------------------------
# ------------------- Functions adapted or copied from Throttlebot -------------------
# ------------------------------------------------------------------------------------
def print_csv_configuration(final_configuration, output_csv='tuned_config.csv'):
    with open(output_csv, 'w') as csvfile:
        fieldnames = ['SERVICE', 'RESOURCE', 'AMOUNT', 'REPR']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for mr in final_configuration:
            result_dict = {}
            result_dict['SERVICE'] = mr.service_name
            result_dict['RESOURCE'] = mr.resource
            result_dict['AMOUNT'] = final_configuration[mr]
            result_dict['REPR'] = 'RAW'
            writer.writerow(result_dict)


# ------------------------------------------------------------------------------------
# --------------------------------------- Main ---------------------------------------
# ------------------------------------------------------------------------------------
if __name__ == '__main__':

    # Setup Logging
    logging.basicConfig(level=logging.INFO)
    logging.info('Started Logging')
    
    sys_config, workload_config, filter_config = parse_config_file("test_config.cfg")
    mr_allocation = parse_resource_config_file(None, sys_config)
    
    baseline = fake_run("test_config.cfg", mr_allocation)
    baseline = sum(baseline) / len(baseline)

    seperator = "-----------------------------------------"
    print seperator
    print "Baseline:", baseline
    print seperator

    tier_resources = identify_tier_resources(mr_allocation)
    def write_config(title, tier_resources, f):
        f.write("{}\n".format(title))
        for i in range(1, 4):
            f.write("    Tier {}: {}\n".format(i, tiers[i]))
            for r in resources:
                f.write("        {}: {}\n".format(r, tier_resources[MR(i, r, [])]))

    with open("./configs/report.txt", "w") as f:  
        write_config("Original Baseline", tier_resources, f)
        trial = 0

        for s in scramble_tiers(tier_resources, 20):
            config = tier_to_configuration(s)
            print_csv_configuration(config, "./configs/config-{}.csv".format(trial))
            config = parse_resource_config_file("./configs/config-{}.csv".format(trial), sys_config)
            t = fake_run("test_config.cfg", config)
            t = sum(t) / len(t)
            print seperator
            print "Baseline:", baseline, "Trial", t
            print seperator
            if t > baseline:
                continue

            write_config("Config {}".format(trial), tier_resources, f)
            trial += 1


