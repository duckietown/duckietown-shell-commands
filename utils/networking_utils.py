import os
import re


def get_ip_from_ping(alias):
    response = os.popen("ping -c 1 %s" % alias).read()
    m = re.search("PING.*?\((.*?)\)+", response)
    if m:
        return m.group(1)
    else:
        raise Exception("Unable to locate %s!" % alias)


def get_duckiebot_ip(duckiebot_name):
    try:
        duckiebot_ip = get_ip_from_ping("%s.local" % duckiebot_name)
    except Exception as e:
        print(e)
        duckiebot_ip = get_ip_from_ping(duckiebot_name)

    return duckiebot_ip
