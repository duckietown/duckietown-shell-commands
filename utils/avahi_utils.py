import json
import time
from types import SimpleNamespace
from zeroconf import ServiceBrowser, Zeroconf

from dt_shell import dtslogger


def wait_for_service(target_service: str, target_hostname: str = None, timeout: int = 10):
    # define callbacks
    workspace = SimpleNamespace(service=target_service, hostname=target_hostname, data=None)

    def cb(service: str, hostname: str, data: dict):
        if target_service == service and target_hostname == hostname:
            workspace.data = data
            workspace.service = service
            workspace.hostname = hostname

    # perform discover
    zeroconf = Zeroconf()
    listener = DiscoverListener(service_in_callback=cb)
    ServiceBrowser(zeroconf, "_duckietown._tcp.local.", listener)
    # wait
    stime = time.time()
    while workspace.data is None:
        time.sleep(0.5)
        if (timeout > 0) and (time.time() - stime > timeout):
            msg = f"No devices matched the search criteria (service={target_service}, hostname={target_hostname})."
            zeroconf.close()
            raise TimeoutError(msg)
    zeroconf.close()
    # ---
    return workspace.service, workspace.hostname, workspace.data


class DiscoverListener:
    def __init__(self, service_in_callback=None, service_out_callback=None):
        self.service_in_callback = service_in_callback
        self.service_out_callback = service_out_callback

    def _process_service(self, zeroconf, type, sname):
        name = sname.replace("._duckietown._tcp.local.", "")
        service_parts = name.split("::")
        if len(service_parts) != 3 or service_parts[0] != "DT":
            return None, None, dict()
        name = "{}::{}".format(service_parts[0], service_parts[1])
        hostname = service_parts[2]
        txt = dict()
        try:
            sinfo = zeroconf.get_service_info(type, sname)
            txt = (
                json.loads(list(sinfo.properties.keys())[0].decode("utf-8"))
                if len(sinfo.properties)
                else dict()
            )
        except:
            pass
        return name, hostname, txt

    def remove_service(self, zeroconf, type, sname):
        name, hostname, txt = self._process_service(zeroconf, type, sname)
        dtslogger.debug(f"Zeroconf:SERVICE_OUT (name={name}, hostname={hostname}, data={txt})")
        if not name:
            return
        if self.service_out_callback:
            self.service_out_callback(name, hostname, txt)

    def add_service(self, zeroconf, type, sname):
        name, hostname, txt = self._process_service(zeroconf, type, sname)
        dtslogger.debug(f"Zeroconf:SERVICE_IN (name={name}, hostname={hostname}, data={txt})")
        if not name:
            return
        if self.service_in_callback:
            self.service_in_callback(name, hostname, txt)
