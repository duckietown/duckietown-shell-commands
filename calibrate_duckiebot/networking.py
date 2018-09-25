import os
import re


def get_ip_from_ping(alias):
    response = os.popen('ping -c 1 %s' % alias).read()
    m = re.search('PING.*?\((.*?)\)+', response)
    if m:
        return m.group(1)
    else:
        raise Exception("Unable to locate %s, aborting!" % alias)


def get_duckiebot_ip(duckiebot_name):
    try:
        mdns_alias = '%s.local' % duckiebot_name
        duckiebot_ip = get_ip_from_ping(mdns_alias)
    except:
        mdns_alias = duckiebot_name
        duckiebot_ip = get_ip_from_ping(mdns_alias)

    return duckiebot_ip
