from nordnm import utils
from nordnm import nordapi

import multiprocessing
from functools import partial
import numpy
import os
import subprocess
from decimal import Decimal
import resource


def generate_connection_name(server, protocol):
    short_name = server['domain'].split('.')[0]
    connection_name = short_name + '.' + protocol + '['

    for i, category in enumerate(server['categories']):
        category_name = nordapi.VPN_CATEGORIES[category['name']]
        if i > 0:  # prepend a separator if there is more than one category
            category_name = '|' + category_name

        connection_name = connection_name + category_name

    return connection_name + ']'


def get_server_score(server, ping_attempts):
    load = server['load']
    domain = server['domain']
    score = 0  # Lowest starting score

    # If a server is at 100% load, we don't need to waste time pinging. Just keep starting score.
    if load < 100:
        rtt, loss = utils.get_rtt_loss(domain, ping_attempts)
        if loss < 5:  # Similarly, if packet loss is >= 5%, the connection is not reliable. Keep the starting score.
            score = round(Decimal(1 / numpy.log(load + rtt)), 4)  # Maximise the score for smaller values of ln(load + rtt)

    return score


def compare_server(server, best_servers, ping_attempts, valid_protocols):
    supported_protocols = []
    if server['features']['openvpn_udp'] and 'udp' in valid_protocols:
        supported_protocols.append('udp')
    if server['features']['openvpn_tcp'] and 'tcp' in valid_protocols:
        supported_protocols.append('tcp')

    country_code = server['flag']
    domain = server['domain']
    score = get_server_score(server, ping_attempts)

    for category in server['categories']:
        category_name = nordapi.VPN_CATEGORIES[category['name']]

        for protocol in supported_protocols:
            best_score = 0

            if best_servers.get((country_code, category_name, protocol)):
                best_score = best_servers[country_code, category_name, protocol]['score']

            if score > best_score:
                name = generate_connection_name(server, protocol)
                best_servers[country_code, category_name, protocol] = {'name': name, 'domain': domain, 'score': score}


def get_num_processes(num_servers):
    # Since each process is not resource heavy and simply takes time waiting for pings, maximise the number of processes (within constraints of the current configuration)

    # Maximum open file descriptors of current configuration
    soft_limit, _ = resource.getrlimit(resource.RLIMIT_NOFILE)

    # Find how many file descriptors are already in use by the parent process
    ppid = os.getppid()
    used_file_descriptors = int(subprocess.run('ls -l /proc/'+str(ppid)+'/fd | wc -l', shell=True, stdout=subprocess.PIPE).stdout.decode('utf-8'))

    # Max processes is the number of file descriptors left, before the sof limit (configuration maximum) is reached
    max_processes = int((soft_limit - used_file_descriptors) / 2)

    if num_servers > max_processes:
        return max_processes
    else:
        return num_servers


def get_best_servers(server_list, ping_attempts, valid_protocols):
    manager = multiprocessing.Manager()
    best_servers = manager.dict()

    num_servers = len(server_list)
    num_processes = get_num_processes(num_servers)

    pool = multiprocessing.Pool(num_processes, maxtasksperchild=1)
    pool.map(partial(compare_server, best_servers=best_servers, ping_attempts=ping_attempts, valid_protocols=valid_protocols), server_list)
    pool.close()

    return best_servers
