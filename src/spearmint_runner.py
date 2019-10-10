import subprocess
import multiprocessing as mp
import time
import json
from datetime import datetime
import os
import shlex
import glob


def run(iterations, time_to_beat):

    date_time = datetime.now()
    subprocess.Popen(shlex.split("mkdir /Users/rahulbalakrishnan/Desktop/data/experiment_run-{}"
                                 .format(date_time.strftime("%m-%d-%Y-%H-%M-%S"))))

    results = []
    trials = []
    best_runs = []

    for _ in range(iterations):

        print("Starting iteration {}".format(_))

        start_time = time.time()

        queue = mp.Queue()


        process_expr = mp.Process(target = run_experiment, args = (queue,))
        process_poll = mp.Process(target=poll_for_best_result, args = (queue, time_to_beat, process_expr))

        process_expr.start()
        process_poll.start()

        process_poll.join()
        process_expr.join()

        print("Saving results for iteration {}".format(_))

        results.append(queue.get() - start_time)

        trials.append(len(glob.glob("/Users/rahulbalakrishnan/Desktop/throttlebot/src/spearmint/bayOptSearch/output/*")))

        best_runs.append(queue.get())

        print("Saving results for iteration {} to disk".format(_))


        subprocess.check_output(["bash ./spearmint/spearmint/save.sh"], shell=True)


    print("Saving aggregate results to disk")

    date_time = datetime.now()
    with open("/Users/rahulbalakrishnan/Desktop/data/threshold/data_{}"
                      .format(date_time.strftime("%m-%d-%Y-%H-%M-%S")), "w") as f:
            dct_to_write = {"time_to_beat": time_to_beat, "data": results, "iterations": iterations,
                            "trials_until_goal": trials, "best_runs": best_runs}
            f.write(json.dumps(dct_to_write))





def run_experiment(queue):
    cmd = "python2.7 ./spearmint/spearmint/main.py --driver=local --method=GPEIOptChooser " + \
                             "--method-args=noiseless=1 --data-file=test.csv /Users/rahulbalakrishnan/Desktop/" + \
                             "throttlebot/src/spearmint/bayOptSearch/bayOpt.pb"

    p = subprocess.Popen(shlex.split(cmd), shell=False)

    queue.put(p)


def poll_for_best_result(queue, time_to_beat, process_to_terminate):

    while True:
        try:
            cmd = "grep \'Best result\' /Users/rahulbalakrishnan/Desktop/throttlebot/src/spearmint/" \
                  "bayOptSearch/best_job_and_result.txt"

            output = str(subprocess.check_output([cmd], shell=True).decode("utf-8"))

            if float(output[13:-1]) < time_to_beat:
                queue.put(time.time())
                queue.put(float(output[13:-1]))
                break
            else:
                time.sleep(5)
        except:
            time.sleep(5)



    p = queue.get()
    p.kill()
    process_to_terminate.terminate()



run(20, 1500)
