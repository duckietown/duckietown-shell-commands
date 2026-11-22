import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from unittest.mock import Mock

from matrix.run.configuration import DTCommandConfiguration as MatrixConfiguration
from matrix.run.map_control import MapControl


class MapControlFixture(unittest.TestCase):
    def setUp(self):
        scratch = TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.folder = Path(scratch.name).resolve()
        self.custom = self.folder / "work maps" / "loop"
        self.custom.mkdir(parents=True)
        (self.custom / "main.yaml").write_text("main: {}")
        self.engine = Mock()
        self.engine.engine.image.id = "sha256:original"
        self.probe = self.engine.engine.client.containers.run
        self.loop_layout = {"tiles": [
            {"kind": "curve", "x": 0.3, "y": 0.3, "width": 0.6, "height": 0.6, "yaw": 0.0}
        ]}
        self.probe.return_value = json.dumps({
            "empty": {"tiles": []},
            "loop": self.loop_layout,
            "sandbox": {"error": "The map preview supports planar tile layouts only."},
        }).encode()
        self.engine.config = {
            "image": "original:tag",
            "command": ["--", "--mode", "gym", "--environments", "2", "--map", "loop"],
            "ports": {"7503/tcp": 7503},
            "volumes": {"/test/shm": {"bind": "/tmp/duckietown/shm", "mode": "rw"}},
        }
        self.original = self.engine.config
        self.control = MapControl(self.engine, self.folder)
        self.addCleanup(self.control.close)

    def apply(self, ticket):
        deadline = monotonic() + 3
        while monotonic() < deadline:
            reply = self.control.apply(ticket)
            if not reply.get("switching"):
                return reply
            sleep(0.01)
        self.fail("The Engine did not finish switching maps.")


class RendererLaunchFixture(unittest.TestCase):
    def setUp(self):
        self.parser = MatrixConfiguration.parser()
        self.shell = Mock()
        self.shell.profile.secrets.dt_token = "unit-test-placeholder"
        self.shell.get_billboard_names.return_value = []
