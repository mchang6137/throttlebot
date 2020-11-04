import argparse
from subprocess import check_output
import re
import requests

REST_URL = '/api/todos'

def delete_posts(website_ip, all_ids):
	url = 'http://' + website_ip + REST_URL + '/'
	for id in all_ids:
		requests.delete(url + id)
	
def GET_from_website(website_ip):
	url = 'http://' + website_ip + REST_URL
	r = requests.get(url).json()
	all_request_ids = []
	for request in r:
		all_request_ids.append(request['_id'])
	return all_request_ids


def clear_all_entries(website_ip):
	all_ids = GET_from_website(website_ip)
	delete_posts(website_ip, all_ids)

if __name__ == "__main__":
	parser = argparse.ArgumentParser()
	parser.add_argument("website_ip")
	parser.add_argument("--clear_db", action="store_true")
	parser.add_argument("--rate", type=int, default=75, help="Number of HTTP requests per second. Defaults to 75.")
	parser.add_argument("--sessions", type=int, default=500, help="Number of sessions. Defaults to 1000")
	parser.add_argument("--burst_to_burst", type=int, default=5, help="Number of seconds between bursts. Defaults to 5.")
	parser.add_argument("--content_file", default="httperf_content", help="The name of the file containing the HTTP POST content.")
	args = parser.parse_args()

	if args.clear_db:
		clear_all_entries(args.website_ip)
	else:
		avg_pat = re.compile("Connection time \[ms\]: min \d+\.\d+ avg (\d+\.\d+) ")
		stddev_pat = re.compile("Connection time \[ms\]: min \d+\.\d+ avg \d+\.\d+ max \d+\.\d+ median \d+\.\d+ stddev (\d+.\d+)")
	
		sess_info = "{},{},{}".format(str(args.sessions), str(args.burst_to_burst), args.content_file)
	
		output = check_output(["httperf", "--server", args.website_ip, "--port", "80", "--rate", str(args.rate),
			"--add-header", "Content-Type:application/json\n", "--wsesslog=" + sess_info])
		output = str(output)
		print("{}".format(output))
	
		avg_m = re.search(avg_pat, output)
		stddev_m = re.search(stddev_pat, output)
	
		print ("AVG: " + avg_m.group(1))
		print ("STDDEV: " + stddev_m.group(1))

