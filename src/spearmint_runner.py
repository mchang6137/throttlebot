import subprocess
import multiprocessing as mp
import time
import json
from datetime import datetime
import os
import shlex
import glob


def run(iterations, time_to_beat, duration, polling_frequency):

    date_time = datetime.now()
    subprocess.Popen(shlex.split("mkdir /Users/rahulbalakrishnan/Desktop/data/experiment_run-{}"
                                 .format(date_time.strftime("%m-%d-%Y-%H-%M-%S"))))

    cumulative_results = []

    for _ in range(iterations):

        iteration_results = []

        print("Starting iteration {}".format(_))

        # start_time = time.time()

        queue = mp.Queue()

        cmd = "python2.7 ./spearmint/spearmint/main.py --driver=local --method=GPEIOptChooser " + \
              "--method-args=noiseless=1 --data-file=test.csv /Users/rahulbalakrishnan/Desktop/" + \
              "throttlebot/src/spearmint/bayOptSearch/bayOpt.pb"

        p = subprocess.Popen(shlex.split(cmd), shell=False)



        process_poll = mp.Process(target=poll_for_best_result, args = (queue, time_to_beat, p, duration,
                                                                       polling_frequency))

        process_poll.start()

        process_poll.join()

        while not queue.empty():
            iteration_results.append(queue.get())

        print("Done with iteration {}".format(_))

        cumulative_results.append(iteration_results)

        subprocess.check_output(["bash ./spearmint/spearmint/save.sh"], shell=True)


    print("Saving aggregate results to disk")

    date_time = datetime.now()
    with open("/Users/rahulbalakrishnan/Desktop/data/threshold/data_{}"
                      .format(date_time.strftime("%m-%d-%Y-%H-%M-%S")), "w") as f:

            f.write(json.dumps({"results": cumulative_results,
                                "polling_frequency": polling_frequency,
                                "duration": duration}))

def poll_for_best_result(queue, time_to_beat, process_to_terminate, duration, polling_frequency):

    starting_time = time.time()
    time_to_compare = starting_time

    first = True
    while time.time() - starting_time < duration:

        try:

            current_time = time.time()
            if current_time - time_to_compare >= polling_frequency:
                time_to_compare = current_time
                cmd = "grep \'Best result\' /Users/rahulbalakrishnan/Desktop/throttlebot/src/spearmint/" \
                      "bayOptSearch/best_job_and_result.txt"

                output = str(subprocess.check_output([cmd], shell=True).decode("utf-8"))
                trial = len(glob.glob("/Users/rahulbalakrishnan/Desktop/throttlebot/src/spearmint/bayOptSearch/output/*"))

                value_to_add = float(output[13:-1])

                if output[13:-1] == "NaN" or value_to_add < 0:
                    raise ValueError

                print("Adding value {} to time data".format(value_to_add))
                queue.put([value_to_add, trial])

                if first:
                    starting_time = current_time
                    first = False

            else:
                time.sleep(max(polling_frequency, 2))

        except:
            time.sleep(max(polling_frequency, 2))






    process_to_terminate.kill()



run(iterations=2, time_to_beat=4000, duration=15*60, polling_frequency=30)
