import csv, random

tiers = {
    1: ["osalpekar/spark-image-compress..."],
    2: ["elasticsearch:2.4", "library/postgres", "tsaianson/node-apt-app", "haproxy:1.7", "hantaowang/logstash-postgres"],
    3: ["kibana:4", "mysql:5"],
}

resources = ["CPU-QUOTA", "DISK", "NET"]

def identify_tier_resources(mr_allocation):
    tier_resources = {}

    for mr, value in mr_allocation.items():
        assert mr.resource in resources
        for tier, lst in tiers.items():
            if mr.service_name in lst:
                tier_mr = MR(tier, mr.resource)
                if tier_mr in tier_resources:
                    assert tier_resources[tier_mr] == value
                else:
                    tier_resources[tier_mr] = value


    for resource in resources:
        total = 0
        for i in range(1, 4):
            total += tier_resources[MR(i, resource)]
        tier_resources[MR(0, resource)] = total

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
                    tier_resources[MR(i, r)] = split[i - 1] * tier_resources[MR(0, r)]
                key.append((r, split))
        if key not in done:
            t += 1
            yield tier_resources.copy()

def tier_to_configuration(tier_resources, config):
    for i in range(1, 4):
        for r in resources:
            value = tier_resources[MR(i, r)]
            for service in tiers[i]:
                config[MR(service, r)] = value
    return config

# ------------------------------------------------------------------------------------
# ------------------- Functions adapted or copied from Throttlebot -------------------
# ------------------------------------------------------------------------------------
class MR:
    def __init__(self, service_name, resource):
        self.service_name = service_name
        self.resource = resource

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.__dict__ == other.__dict__
        else:
            return False

    def __hash__(self):
        return hash((self.service_name, self.resource))

    def __repr__(self):
        return str((self.service_name, self.resource))

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


def parse_resource_config_file(resource_config_csv):

    mr_allocation = {}

    # Manual Configuration Possible
    # Parse a CSV
    # Format of resource allocation: SERVICE,RESOURCE,TYPE,REPR
    with open(resource_config_csv, 'rb') as resource_config:
        reader = csv.DictReader(resource_config)

        for row in reader:
            service_name = row['SERVICE']
            resource = row['RESOURCE']
            amount = float(row['AMOUNT'])
            amount_repr = row['REPR']

            assert amount_repr == 'RAW'

            mr = MR(service_name, resource)
            mr_allocation[mr] = amount

    return mr_allocation

# ------------------------------------------------------------------------------------
# --------------------------------------- Main ---------------------------------------
# ------------------------------------------------------------------------------------
if __name__ == '__main__':
    mr_allocation = parse_resource_config_file("tuned_config.csv")
    tier_resources = identify_tier_resources(mr_allocation)
    def write_config(title, tier_resources, f):
        f.write("{}\n".format(title))
        for i in range(1, 4):
            f.write("    Tier {}: {}\n".format(i, tiers[i]))
            for r in resources:
                f.write("        {}: {}\n".format(r, tier_resources[MR(i, r)]))

    with open("./configs/report.txt", "w") as f:  
        write_config("Original Baseline", tier_resources, f)
        trial = 0

        for s in scramble_tiers(tier_resources, 10):
            write_config("Config {}".format(trial), tier_resources, f)
            trial += 1
            config = tier_to_configuration(s, mr_allocation)
            print_csv_configuration(config, "./configs/config-{}.csv".format(trial))


