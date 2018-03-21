import argparse
import requests
import json

REST_URL = '/api/todos'

def delete_posts(website_ip, all_ids):
    url = 'http://' + website_ip + REST_URL + '/'
    for ids in all_ids:
        requests.delete(url + ids)
    return 1

def GET_from_website(website_ip):
    url = 'http://' + website_ip + REST_URL
    r = requests.get(url).json()
    all_request_ids = []
    for request in r:
        all_request_ids.append(request['_id'])
    return all_request_ids


def clear_all_entries(website_ip):
    all_ids = GET_from_website(website_ip)
    fin = delete_posts(website_ip, all_ids)
    return fin

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("website_ip")
    args = parser.parse_args()

    fin = clear_all_entries(args.website_ip)

    all_ids = GET_from_website(args.website_ip)
    prev = len(all_ids)
    counter = 0
    while prev != 0 and counter < 100:
        all_ids = GET_from_website(args.website_ip)
        if prev == len(all_ids):
            counter += 1
        prev = len(all_ids)

    if len(all_ids) == 0:
        clear_all_entries(args.website_ip)

    print("Cleared entries! "+str(fin))