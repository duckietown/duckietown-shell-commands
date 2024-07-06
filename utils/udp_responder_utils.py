import asyncio
import dataclasses
import ipaddress
import json
import socket
from typing import Tuple, Dict, List, Optional, Callable

import netifaces

from dt_shell import dtslogger

IPAddress = str
Port = int
IFace = str
FullAddress = Tuple[IPAddress, Port]

LOCAL_HOST = '0.0.0.0'
REMOTE_PORT = 11411


@dataclasses.dataclass
class Packet:
    version: str

    def asdict(self) -> dict:
        return dataclasses.asdict(self)

    def serialize(self) -> bytes:
        return json.dumps(dataclasses.asdict(self)).encode()

    @classmethod
    def deserialize(cls, data: bytes):
        try:
            return cls(**json.loads(data))
        except Exception:
            raise ValueError(f"Could not deserialize data: {data}")


@dataclasses.dataclass
class PingPacket(Packet):
    # port where the client is listening for pong packets
    port: Port


@dataclasses.dataclass
class PongPacket(Packet):
    name: str
    type: str
    configuration: str
    hardware: str


class PongReceiver(asyncio.DatagramProtocol):

    def __init__(self, callback: Callable[[FullAddress, PongPacket], None] = None):
        self._callback: Callable[[FullAddress, PongPacket], None] = callback

    def datagram_received(self, data: bytes, addr: Tuple[IPAddress, Port]):
        host, _ = addr
        # decode the packet
        try:
            pong = PongPacket.deserialize(data)
        except ValueError as e:
            dtslogger.warning(e.args[0])
            return
        # detected robot
        dtslogger.debug(f"Received pong from {addr}: {pong.asdict()}")
        self._callback(addr, pong)


class UDPScanner:

    def __init__(self, brute: bool = False, max_ips_per_interface: int = 256):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._port: int = 0
        self._stopped: bool = False
        self._max_ips_per_interface = max_ips_per_interface
        # find all potentially useful IPs
        self._all_ips = self.get_all_candidate_ips(brute=brute)

    def stop(self):
        self._stopped = True

    async def send_ping(self, host: str):
        # formulate the ping packet
        ping = PingPacket(version='1', port=self._port)
        # send the ping packet
        # dtslogger.debug(f"Sending ping to {host}:{REMOTE_PORT}")
        self._sock.sendto(ping.serialize(), (host, REMOTE_PORT))

    async def scan(self, callback: Callable[[FullAddress, PongPacket], None]):
        loop = asyncio.get_event_loop()
        # create the receiver
        transport, _ = await loop.create_datagram_endpoint(
            lambda: PongReceiver(callback), local_addr=(LOCAL_HOST, 0))
        # get the port assigned by the OS
        self._port = transport.get_extra_info('socket').getsockname()[1]
        # send pings to all IPs
        for _, ips in self._all_ips.items():
            count = 0
            for ip in ips:
                if self._stopped:
                    break
                await self.send_ping(ip)
                count += 1
                # every 10 pings sent, pass the ball to the listener to consume the responses (if any)
                if count % 10 == 0:
                    await asyncio.sleep(0.001)
                # limit the total number of pings sent to each interface
                if count > self._max_ips_per_interface:
                    break

    @classmethod
    def get_all_candidate_ips(cls, brute: bool, skip_unlikely: bool = True, max_netmask_length: int = 16) \
            -> Dict[IFace, List[IPAddress]]:
        result = {}

        # get the default gateway for IPv4 (if any)
        gateway: Optional[Tuple[IPAddress, IFace]] = \
            netifaces.gateways().get("default", {}).get(netifaces.AF_INET, None)

        # start from no interfaces
        ifaces = []
        all_ifaces = netifaces.interfaces()

        # if we have a gateway, use it
        if gateway:
            ifaces = [gateway[1]]

        # if we have a docker0 interface, use it (this is needed to support virtual robots)
        if "docker0" in all_ifaces:
            ifaces.append("docker0")

        # if brute force is enabled, use all interfaces
        if brute:
            ifaces = all_ifaces
            # skip bridges, virtual interfaces, and virtual bridges (if requested)
            if skip_unlikely:
                ifaces = [
                    iface for iface in ifaces
                    if not (iface.startswith("br-") or iface.startswith("veth") or iface.startswith("virbr"))
                ]

        # for each interface, get all IPv4 addresses
        for iface in ifaces:
            ips = netifaces.ifaddresses(iface).get(netifaces.AF_INET, [])
            result[iface] = []

            # for each address, get all IPs in the subnet
            for ip in ips:
                # limit to 'small' subnets
                mask_len = ipaddress.IPv4Network(f"0.0.0.0/{ip['netmask']}").prefixlen
                if mask_len < max_netmask_length:
                    continue

                # get all IPs in the subnet
                all_iface_ips = list(iter(ipaddress.IPv4Network((ip["addr"], ip["netmask"]), strict=False)))

                # remove the network and broadcast addresses
                all_iface_ips = all_iface_ips[1:-1]

                # add them to the result
                result[iface] += [str(ip) for ip in all_iface_ips]

        # ---
        return result
