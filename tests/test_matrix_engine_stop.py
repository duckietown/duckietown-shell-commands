from threading import Event, Thread
from unittest.mock import Mock

import requests
from docker.errors import NotFound

from matrix.run.map_control import (
    ENGINE_STOP_PATH,
    MAP_CONTROL_HEADER,
    MapControlHTTPServer,
)
from tests.matrix_fixtures import MapControlFixture


class MatrixEngineStopTests(MapControlFixture):
    def test_stop_ticket_cannot_stop_a_replacement_container(self):
        ticket = self.control.prepare_stop()["ticket"]
        self.engine.stop.assert_not_called()
        self.engine.engine = Mock()
        with self.assertRaisesRegex(ValueError, "previous Engine changed"):
            self.control.stop(ticket)
        self.engine.stop.assert_not_called()

    def test_stop_request_keeps_browser_frontend_alive(self):
        container = self.engine.engine
        exiting = Event()
        waiting = Event()

        def wait_for_exit():
            waiting.set()
            exiting.wait(4)

        def stop_engine():
            self.engine.engine = None
            exiting.set()

        container.wait.side_effect = wait_for_exit
        container.reload.side_effect = NotFound("already removed")
        self.engine.stop.side_effect = stop_engine
        browser_result = []
        browser_waiter = Thread(target=lambda: browser_result.append(self.control.wait_for_engine()))
        browser_waiter.start()
        self.addCleanup(browser_waiter.join)
        self.addCleanup(exiting.set)
        self.assertTrue(waiting.wait(2))
        with MapControlHTTPServer(self.control) as server:
            thread = Thread(target=server.serve_forever)
            thread.start()
            try:
                origin = f"http://127.0.0.1:{server.server_port}"
                url = origin + ENGINE_STOP_PATH
                headers = {MAP_CONTROL_HEADER: self.control.token, "Origin": origin}
                self.assertEqual(requests.post(url, json={}, timeout=3).status_code, 403)
                self.assertEqual(requests.get(url, headers=headers, timeout=3).status_code, 405)
                invalid = requests.post(url, json={"container": "other"}, headers=headers, timeout=3)
                self.assertEqual(invalid.status_code, 400)
                prepared = requests.post(url, json={}, headers=headers, timeout=3)
                self.assertEqual(prepared.status_code, 200)
                self.engine.stop.assert_not_called()
                request = {"ticket": prepared.json()["ticket"]}
                self.assertEqual(requests.post(url, json=request, headers=headers, timeout=3).status_code, 202)
                browser_waiter.join(3)
                self.assertEqual(browser_result, [False])
                self.assertEqual(requests.post(url, json=request, headers=headers, timeout=3).json(), {"ready": True})
                self.engine.stop.assert_called_once()
                self.engine.start.assert_not_called()
            finally:
                server.shutdown()
                thread.join()
