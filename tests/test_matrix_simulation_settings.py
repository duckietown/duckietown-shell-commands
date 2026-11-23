from time import monotonic
from unittest.mock import patch

from matrix.run.map_control import MapControl
from tests.matrix_fixtures import MapControlFixture


class MatrixSimulationSettingsTests(MapControlFixture):
    def test_simulation_restart_and_later_map_change_keep_runtime_settings_and_ports(self):
        draft = {"mode": "gym", "environments": 3, "delta_t": 0.015}
        ticket = self.control.prepare_engine_settings(draft)["ticket"]
        self.assertEqual(self.probe.call_args.args[1][-2:], ["loop", "3"])
        self.engine.stop.assert_not_called()
        self.assertTrue(self.apply(ticket)["ready"])
        self.assertEqual(self.control.status()["engine_settings"], draft)
        self.assertEqual(self.control.status()["factory_engine_settings"],
                         {"mode": "realtime", "environments": 1, "delta_t": 0.0})
        command = self.engine.config["command"]
        self.assertEqual(command[command.index("--environments") + 1], "3")
        self.assertEqual(command[command.index("--delta-t") + 1], "0.015")
        self.assertEqual(self.engine.config["ports"], self.original["ports"])
        self.assertTrue(self.apply(self.control.prepare({"embedded": True, "value": "empty"})["ticket"])["ready"])
        self.assertEqual(self.probe.call_args.args[1][-2:], ["empty", "3"])
        factory = self.control.status()["factory_engine_settings"]
        self.assertTrue(self.apply(self.control.prepare_engine_settings(factory)["ticket"])["ready"])
        self.assertNotIn("--environments", self.engine.config["command"])
        self.assertNotIn("--delta-t", self.engine.config["command"])
        self.assertEqual(self.control.status()["current"]["value"], "empty")

    def test_invalid_expired_and_failed_simulation_changes_do_not_replace_saved_settings(self):
        saved = self.control.status()["engine_settings"]
        for draft in (
            {**saved, "environments": True}, {**saved, "environments": 0},
            {**saved, "delta_t": float("inf")}, {**saved, "delta_t": -1},
            {**saved, "mode": "realtime", "delta_t": 0.01}, {**saved, "unknown": []},
        ):
            with self.subTest(draft=draft), self.assertRaises(ValueError):
                self.control.prepare_engine_settings(draft)
        change = {**saved, "mode": "realtime", "environments": 1}
        with patch("matrix.run.map_control.monotonic", return_value=monotonic() - 61):
            ticket = self.control.prepare_engine_settings(change)["ticket"]
        self.assertIn("expired", self.control.apply(ticket)["error"])
        self.engine.stop.assert_not_called()
        self.engine.wait_until_healthy.side_effect = [TimeoutError(), None]
        result = self.apply(self.control.prepare_engine_settings(change)["ticket"])
        self.assertTrue(result["ready"])
        self.assertIn("previous simulation settings were restored", result["error"])
        self.assertEqual(self.control.status()["engine_settings"], saved)
        self.assertEqual(self.engine.config["command"], self.original["command"])

    def test_launch_constraints_survive_settings_edits(self):
        self.engine.config = {**self.original, "environment": {"DTSHELL_SHM_PATH": "/private/gym"},
                              "command": ["--", "--mode", "gym", "--map", "loop", "--link", "map_0/vehicle_0", "bot"]}
        control = MapControl(self.engine, self.folder)
        self.addCleanup(control.close)
        catalog = control.status()
        self.assertTrue(catalog["gym_only"])
        self.assertFalse(catalog["can_replicate"])
        self.assertEqual(catalog["factory_engine_settings"]["mode"], "gym")
        with self.assertRaisesRegex(ValueError, "shared memory"):
            control.prepare_engine_settings({"mode": "realtime", "environments": 1, "delta_t": 0})
        with self.assertRaisesRegex(ValueError, "physical links"):
            control.prepare_engine_settings({"mode": "gym", "environments": 2, "delta_t": 0})
        self.engine.stop.assert_not_called()
