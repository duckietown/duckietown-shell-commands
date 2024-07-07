from dt_shell import DTCommandAbs, dtslogger, DTShell
from duckietown_messages.simulation.hil.configuration import HILConfiguration
from duckietown_messages.simulation.hil.connection.configuration import HILConnectionConfiguration
from utils.kvstore_utils import KVStore


class DTCommand(DTCommandAbs):

    help = f'Detaches a world robot from the Duckiematrix'

    @staticmethod
    def command(shell: DTShell, args, **kwargs):
        parsed = kwargs.get("parsed", None)
        if parsed is None:
            parsed = DTCommand.parser.parse_args(args)
        # ---
        parsed.robot = parsed.robot[0]
        # set the HIL configuration
        hil_cfg: HILConfiguration = HILConfiguration()
        hil_conn: HILConnectionConfiguration = HILConnectionConfiguration(simulator=None, agent_name="")
        kv: KVStore = KVStore(parsed.robot)
        # ask the world robot to join the network
        try:
            dtslogger.info(f"Requesting robot '{parsed.robot}' to detach from the Duckiematrix...")
            # set the configuration first, then the connection, order matters here to avoid robots acting on an old cfg
            kv.set("hil/configuration", hil_cfg)
            kv.set("hil/connection", hil_conn)
            dtslogger.info("Request sent, robot should now detach.")
        except BaseException as e:
            dtslogger.error("An error occurred while contacting the robot.\n"
                            f"The error reads:\n{e}")
            return

    @staticmethod
    def complete(shell, word, line):
        return []
