#Throttlebot!

The advent of accessible open source software and lightweight virtualized containers have led to the widespread adoption of complex software services like Spark or Redis. In spite of the popularity of these services, performance tuning for these services are usually managed by provisioning large teams of manual labor for the problem. The manpower required for this makes it highly unfeasible for the vast majority of organizations. We propose ThrottleBot which identifies performance bottlenecks for a containerized service by systematically throttling the container resources. Ultimately, this makes it possible to intelligently provision containers while allowing the user to treat the system as a black box. ThrottleBot successfully identifies the bottleneck in a variety of widely used services, including Nginx, Spark, and the MEAN stack.ThrottleBot!

ThrottleBot builds off of the Berkeley Quilt Project, which can be found at quilt.io


Instructions on how to use ThrottleBot:

For an example of an acceptable Throttlebot setup, please see test_config.cfg, which is an example of a nginx workload.

Dependencies:
- Redis: https://redis.io/topics/quickstart
Start the Redis server before running Throttlebot as in the instructions described in the quickstart.
- Quilt: https://github.com/mchang6137/quilt
Quilt is a container orchestrator that can be used to deploy a distributed application. Please see the docs on how to install and deploy the application on Quilt.

Steps to run Throttlebot:

1. To run Throttlebot, please create a configuration file. test_config.cfg serves as an example of how such a file would look. All parameters specified are mandatory and parameters that require multiple values should be comma-separated, without spaces

The "Basic" Section describes general Throttlebot parameters.

- baseline_trials: The number of experiment trials to run for the baseline experiment
- trials: The number of trials to run each of the stressed experiments (you might feel inclined to choose fewer trials than experiment_trials for faster experimenting
- increments: Describes how many levels of stressing. An increment of 20 s
stress_these_resources: The resources that are good to consider. Current options so far are only DISK, NET, CPU-CORE, MEMORY, and CPU-QUOTA. 
- stress_these_services: The names of the services you would want Throttlebot to stress. To stress all services,simply indicate *. Throttlebot will blacklist any non-application related services by default
redis_host: The host where the Redis is located (Throttlebot uses Redis as it's data store)
- stress_policy: The policy that is being used by Throttlebot to decide which containers to consider on each iteration. Note: the only policy implemented right now is 'ALL'
- gradient_mode: This decides the gradient mode that is being used by Throttlebot. The two options \
are 'single and 'inverted'.

The "Workload" section describes several Workload specific parameters. Throttlebot will run the experiment in this manner on each iteration.

- type: Each implemented workload will have a type. Set the experiment name here. This might be deprecated later.
request_generator: An instance that generates requests to the application under test. There might be multiple of these instances. This is most likely an Ip address or a hostname.
- frontend: The host name (or IP address) where the application frontend is. This is an IP address or hostname.
additional_args: The names of any additional arguments that would be used by this workload
- additional_arg_values: The values of the additional arguments (see additional_args above), listed in the same order as the argument names in additional_args
- tbot_metric: The experiment could return several metrics, but this tells Throttlebot which metric to prioritize MIMRs by. There can only be a single metric here. Ensure that the metric is spelled identically as in your workload.py
- performance_target: A termination point for Throttlebot. This is for Throttlebot to know when to stop running the experiments. This is not yet implemented.

2.) One also has the option of setting an initial resource configuration.
- If the user does not pass in a resource configuration (i.e., python run_throttlebot.py --config_file test_config.py), then Throttlebot will automatically provision some hard resource limits to the application. Throttlebot will find the maximum capacity of MR,halve it, and divide it by the the machine with the highest number of containers. This will ensure that there is room to scale resource provisioning up and down for the purposes of testing.
- The user also has the option of passing in a resource configuration as a CSV file. The CSV file has 4 fields.
  - SERVICE: The service name
  - RESOURCE: The resource name (These names have the same restrictions as the ones named in the Throttlebot configuration file. (SERVICE, RESOURCE), is an MR
  - AMOUNT: The amount provisioned to the MR
  - REPR: This can be either RAW or PERCENT. RAW indicates the exact raw amount of resource being provisioned to the system, while PERCENT indicates the percent of the raw capacity of the machine. 
There must be an entry for every MR present in the system

3.) The "Filter" section describes Filter specific parameters that Throttlebot will use to prune the \
search space. There is currently only a single filter_policy.
- filter_policy: the type of filtering policy that you want. If there is no entry for the filter po\
licy, then no filtering will be used.
stress_amount: how much the resources that are being jointly stressed (i.e., the pipelines) are s\
tressed.
- filter_exp_trials: the number of trials you want to do for the filter policy
pipeline_services: the services that should be stressed together. Separate the pipelines by comma\
s, and the individual services within a pipeline by dashes. For example: "Sparkstreaming-haproxy-\
mongo,nginx-redis". If you're too lazy to specify particular services to be in a pipeline, there \
are defaults. The default options are as follows.
    1.) BY_SERVICE will simply treat each service as a pipeline (i.e., stress all MRs that are part of each service).
  2) RANDOM: This will create n groups of random partitions of MRs and stress those as MRs. n is set by pipeline_partitions
- pipeline_partitions: see the pipeline_services option

Once the configuration is set, ensure Redis is up and running, and then start Throttlebot with the following command.

$ python run_throttlebot.py <config_file_name>

2. If necessary, set the "password" variables for your SSH keys. Without this, Throttlebot cannot execute commands on the virtual machines. They are located within remote_execution.py and measure_performance_MEAN_py3.py.