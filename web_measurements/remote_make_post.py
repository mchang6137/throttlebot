import json
import requests
import argparse
import datetime
import csv
from multiprocessing.dummy import Pool as ThreadPool

REST_URL = '/api/todos'

def POST_to_website(website_ip, num_iterations, num_threads):
	# create request object, set url and post data
	requests = [website_ip] * num_iterations
	pool = ThreadPool(num_threads)
	all_request_times = pool.map(make_single_POST, requests)
	return all_request_times

def make_single_POST(website_ip):
	url = 'http://' + website_ip + REST_URL
	current_date = datetime.datetime.now()
	data = {'text': str(current_date)}
	headers = {'Content-type': 'application/json'}
	request_time = requests.post(url, data=json.dumps(data), headers=headers).elapsed.total_seconds()
	return request_time

def write_results(times):
	with open("times.csv", "w") as f:
		writer = csv.writer(f)
		writer.writerow(times)

if __name__ == "__main__":
	parser = argparse.ArgumentParser()
	parser.add_argument("website_ip")
	parser.add_argument("--iterations", type=int, default=100, help="Number of HTTP requests to send the REST server")
	parser.add_argument("--threads", type=int, default=4, help="Number of threads used to execute the HTTP requests")
	args = parser.parse_args()

	times = POST_to_website(args.website_ip,args. iterations, args.threads)
	write_results(times)	
