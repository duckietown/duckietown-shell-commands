import requests
from dt_shell import DTCommandAbs, dtslogger, DTShell, UserError
from dtps_http import CONTENT_TYPE_DTPS_DATAREADY_CBOR

from utils.kvstore_utils import KVStore, KVStoreUnreachable
from utils.networking_utils import get_default_gateway_and_interface, get_interface_ip_address

from duckietown_messages.simulation.hil.connection.configuration import HILConnectionConfiguration
from duckietown_messages.simulation.hil.configuration import HILConfiguration
from duckietown_messages.network.dtps.context import DTPSContextMsg


DEFAULT_DUCKIEMATRIX_ENGINE_PORT = 7501
ATTACH_TIMEOUT = 3.0


def _reserve_entity(kv: KVStore, robot: str, entity: str, engine_url: str) -> None:
    try:
        identity = kv.get(dict, "hil/identity", None)
    except (KVStoreUnreachable, requests.RequestException) as error:
        raise UserError(f"Could not read the HIL identity of robot '{robot}': {error}") from error
    except (ValueError, KeyError) as error:
        raise UserError(f"Robot '{robot}' returned an invalid HIL identity.") from error
    name = None if identity is None else identity.get("robot")
    if not isinstance(name, str) or not name:
        raise UserError(
            f"Robot '{robot}' does not publish its name in the HIL identity. "
            "Update the robot interface and make sure its Duckiematrix interface is running."
        )
    robot_type = identity.get("robot_type")
    configuration = identity.get("configuration")
    if (not isinstance(robot_type, str) or robot_type in ("", "unknown")
            or not isinstance(configuration, str) or configuration in ("", "UNKNOWN")):
        raise UserError(f"Robot '{robot}' did not report a valid robot type and configuration.")

    try:
        reply = requests.post(
            f"{engine_url}hil/reserve/",
            json={"entity": entity, "robot": name, "robot_type": robot_type, "configuration": configuration},
            timeout=ATTACH_TIMEOUT,
            allow_redirects=False,
        )
    except requests.RequestException as error:
        raise UserError(f"Could not reserve the entity with the Engine at {engine_url}: {error}") from error
    if reply.status_code in (400, 409, 422):
        raise UserError(f"Cannot attach robot '{robot}': {reply.text}")
    if reply.status_code == 404:
        raise UserError("The Engine does not support reserving HIL entities. Update the Duckiematrix Engine.")
    if reply.status_code != 201 or reply.headers.get("Content-Type") != CONTENT_TYPE_DTPS_DATAREADY_CBOR:
        raise UserError(f"The Engine did not confirm the HIL reservation (HTTP {reply.status_code}).")


class DTCommand(DTCommandAbs):

    help = f'Attaches a world robot to an existing Duckiematrix agent'

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = DTCommand._resolve_parsed(args, kwargs.get("parsed"))
        # ---
        parsed.robot = parsed.robot[0]
        parsed.entity = parsed.entity[0]
        # get IP address on the gateway network interface
        if parsed.engine_hostname is None:
            dtslogger.info("Engine hostname not given, assuming the engine is running "
                           "on the local machine.")
            _, default_interface = get_default_gateway_and_interface()
            if default_interface is None:
                dtslogger.warning("An error occurred while figuring out the gateway interface.\n"
                                  f"Will assume that the robots can reach the engine at the "
                                  f"hostname 'localhost'.")
                engine_hostname = "localhost"
            else:
                dtslogger.info(f"Found gateway interface: {default_interface}")
                dtslogger.info("Figuring out the IP address...")
                engine_hostname = get_interface_ip_address(default_interface)
                dtslogger.info(f"IP address found: {engine_hostname}")
        else:
            engine_hostname = parsed.engine_hostname
        engine_url = f"http://{engine_hostname}:{DEFAULT_DUCKIEMATRIX_ENGINE_PORT}/"
        kv = KVStore(parsed.robot, timeout=ATTACH_TIMEOUT)
        _reserve_entity(kv, parsed.robot, parsed.entity, engine_url)
        hil_conn: HILConnectionConfiguration = HILConnectionConfiguration(
            simulator=DTPSContextMsg(
                name="duckiematrix",
                urls=[engine_url],
                path="/robot/",
            ),
            agent_name=parsed.entity,
        )
        hil_cfg: HILConfiguration = HILConfiguration(
            dreamwalking=parsed.dreamwalk,
        )
        # ask the world robot to join the network
        try:
            dtslogger.info(f"Requesting robot '{parsed.robot}' to attach to entity '{parsed.entity}' on "
                           f"Duckiematrix engine at {engine_hostname}...")
            # set the configuration first, then the connection, order matters here to avoid robots acting on an old cfg
            kv.set("hil/configuration", hil_cfg)
            kv.set("hil/connection", hil_conn)
            dtslogger.info("Request sent, robot should now connect.")
        except (KVStoreUnreachable, requests.RequestException) as error:
            raise UserError(f"Could not request attachment on robot '{parsed.robot}': {error}") from error

    @staticmethod
    def complete(shell, word, line):
        return []
