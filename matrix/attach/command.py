from dt_shell import DTCommandAbs, dtslogger, DTShell

from utils.kvstore_utils import KVStore
from utils.networking_utils import get_default_gateway_and_interface, get_interface_ip_address

from duckietown_messages.simulation.hil.connection.configuration import HILConnectionConfiguration
from duckietown_messages.simulation.hil.configuration import HILConfiguration
from duckietown_messages.network.dtps.context import DTPSContextMsg


DEFAULT_DUCKIEMATRIX_ENGINE_PORT = 7501


class DTCommand(DTCommandAbs):

    help = f'Attaches a world robot to an existing Duckiematrix agent'

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = kwargs.get("parsed", None)
        if parsed is None:
            parsed = DTCommand.parser.parse_args(args)
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
        # set the HIL configuration
        hil_conn: HILConnectionConfiguration = HILConnectionConfiguration(
            simulator=DTPSContextMsg(
                name="duckiematrix",
                urls=[f"http://{engine_hostname}:{DEFAULT_DUCKIEMATRIX_ENGINE_PORT}/"],
                path="/robot/",
            ),
            agent_name=parsed.entity,
        )
        hil_cfg: HILConfiguration = HILConfiguration(
            dreamwalking=parsed.dreamwalk,
        )
        kv: KVStore = KVStore(parsed.robot)
        # ask the world robot to join the network
        try:
            dtslogger.info(f"Requesting robot '{parsed.robot}' to attach to entity '{parsed.entity}' on "
                           f"Duckiematrix engine at {engine_hostname}...")
            # set the configuration first, then the connection, order matters here to avoid robots acting on an old cfg
            kv.set("hil/configuration", hil_cfg)
            kv.set("hil/connection", hil_conn)
            dtslogger.info("Request sent, robot should now connect.")
        except BaseException as e:
            dtslogger.error("An error occurred while contacting the robot.\n"
                            f"The error reads:\n{e}")
            return

    @staticmethod
    def complete(shell, word, line):
        return []
