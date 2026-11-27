import logging
import socket
import threading
import time
import unittest
from unittest.mock import patch

import requests
from docker.errors import NotFound
from dt_shell import UserError

import utils.docker_utils as du

HEARTBEAT = 0.2
TIMINGS = dict(
    PULL_PROGRESS_HEARTBEAT_SECONDS=HEARTBEAT,
    PULL_PING_TIMEOUT_SECONDS=0.01,
    PULL_RECONNECT_TIMEOUT_SECONDS=0.3,
    PULL_STUCK_TIMEOUT_SECONDS=1.5,
    PULL_READER_JOIN_TIMEOUT_SECONDS=0.01,
)
DONE = {"status": "Status: Downloaded newer image for x:y"}
HANG = "hang"


def line(layer, status, current=None):
    event = {"id": layer, "status": status}
    if current is not None:
        event["progressDetail"] = {"current": current, "total": 10**9}
    return event


def chatter(seconds, step=0.05):
    # Docker keeps sending lines but no byte moves
    return [x for _ in range(int(seconds / step)) for x in (line("L1", "Waiting"), step)]


def downloading(seconds, step, start=0):
    return [x for i in range(int(seconds / step)) for x in (line("L1", "Downloading", start + i + 1), step)]


COMPLETE = [line("L1", "Download complete"), line("L1", "Pull complete"), DONE]


class _Stream:
    def __init__(self):
        self.cut = threading.Event()


class FakeEndpoint:
    """The robot's Docker: each pull request gets the next scripted stream (the last one repeats).

    A script is a list of Docker lines (dict), pauses (seconds), exceptions raised by the stream,
    or HANG (block until dts cuts the stream). The end of the list is EOF.
    """

    def __init__(self, *scripts, answers=None):
        self.scripts = list(scripts)
        self.answers = answers or (lambda: True)
        self.opens = 0
        self.log = []

    def open(self, client, image):
        script = self.scripts[min(self.opens, len(self.scripts) - 1)]
        self.opens += 1
        if isinstance(script, Exception):
            raise script
        stream = _Stream()
        return stream, self._play(script, stream)

    def _play(self, script, stream):
        for item in script:
            if item is HANG:
                stream.cut.wait()
                raise requests.exceptions.ConnectionError("cut")
            if isinstance(item, Exception):
                raise item
            if isinstance(item, (int, float)):
                time.sleep(item)
                continue
            yield item

    def cut(self, stream):
        self.log.append("cut")
        stream.cut.set()

    @property
    def cuts(self):
        # cuts made while the pull was still running, not the cleanup after the last attempt
        last = max((i for i, event in enumerate(self.log) if event == "attempt ended"), default=0)
        return self.log[:last].count("cut")


class PullRetryTests(unittest.TestCase):
    def setUp(self):
        for name, value in TIMINGS.items():
            patcher = patch.object(du, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        level = du.dtslogger.level
        du.dtslogger.setLevel(logging.ERROR)
        self.addCleanup(du.dtslogger.setLevel, level)
        self.client = object.__new__(du.DockerClientOLD)

    def pull(self, robot):
        attempt = du._pull_image_once_OLD

        def logged_attempt(*args):
            try:
                attempt(*args)
            finally:
                robot.log.append("attempt ended")

        with patch.object(du, "_open_pull_stream", robot.open), patch.object(
            du, "_cut_pull_stream", robot.cut
        ), patch.object(du, "_endpoint_answers", lambda client: robot.answers()), patch.object(
            du, "_pull_image_once_OLD", logged_attempt
        ):
            started = time.monotonic()
            try:
                du.pull_image_OLD("x:y", endpoint=self.client, progress=False)
            finally:
                self.elapsed = time.monotonic() - started

    def test_normal_pull(self):
        robot = FakeEndpoint([line("L1", "Pulling fs layer"), line("L1", "Downloading", 1)] + COMPLETE)
        self.pull(robot)
        self.assertEqual(robot.opens, 1)

    def test_big_layer_that_keeps_moving(self):
        robot = FakeEndpoint(downloading(4 * HEARTBEAT, HEARTBEAT / 2) + COMPLETE)
        self.pull(robot)
        self.assertEqual(robot.opens, 1)

    def test_quiet_stream_shorter_than_a_stall(self):
        robot = FakeEndpoint(
            [line("L1", "Downloading", 1), 1.5 * HEARTBEAT, line("L1", "Downloading", 2)] + COMPLETE
        )
        self.pull(robot)
        self.assertEqual(robot.opens, 1)

    def test_chatter_without_progress_reattaches(self):
        robot = FakeEndpoint(chatter(3 * HEARTBEAT), [line("L1", "Downloading", 1)] + COMPLETE)
        self.pull(robot)
        self.assertEqual(robot.opens, 2)
        # the second stream moved bytes, so the first one is closed; the download itself is never cut
        self.assertEqual(robot.cuts, 1)

    def test_robot_gone_and_back(self):
        pings = iter([False, False, False])
        robot = FakeEndpoint(
            [line("L1", "Downloading", 1), HANG], COMPLETE, answers=lambda: next(pings, True)
        )
        self.pull(robot)
        self.assertEqual(robot.opens, 2)

    def test_broken_stream(self):
        robot = FakeEndpoint(
            [line("L1", "Downloading", 1), requests.exceptions.ChunkedEncodingError()], COMPLETE
        )
        self.pull(robot)
        self.assertEqual(robot.opens, 2)

    def test_cut_stream(self):
        robot = FakeEndpoint([line("L1", "Downloading", 1), line("L2", "Downloading", 1)], COMPLETE)
        self.pull(robot)
        self.assertEqual(robot.opens, 2)

    def test_eof_after_the_seen_layers_finished_but_before_the_final_status_retries(self):
        robot = FakeEndpoint(
            [line("L1", "Already exists")], [line("L1", "Already exists"), line("L2", "Pull complete"), DONE]
        )
        self.pull(robot)
        self.assertEqual(robot.opens, 2)

    def test_no_space_fails_at_once(self):
        robot = FakeEndpoint([{"error": "write /var/lib/docker/tmp: no space left on device"}])
        with self.assertRaisesRegex(UserError, "no space left"):
            self.pull(robot)
        self.assertEqual(robot.opens, 1)

    def test_io_error_fails_at_once(self):
        robot = FakeEndpoint([{"error": "read /var/lib/docker: input/output error"}])
        with self.assertRaisesRegex(UserError, "input/output error"):
            self.pull(robot)
        self.assertEqual(robot.opens, 1)

    def test_tls_timeout_retries(self):
        robot = FakeEndpoint([{"error": "net/http: TLS handshake timeout"}], COMPLETE)
        self.pull(robot)
        self.assertEqual(robot.opens, 2)

    def test_network_errors_retry(self):
        for error in (
            "dial tcp 1.2.3.4:443: connect: connection timed out",
            "dial tcp 1.2.3.4:443: connect: no route to host",
            "context deadline exceeded",
        ):
            with self.subTest(error=error):
                robot = FakeEndpoint([{"error": error}], COMPLETE)
                self.pull(robot)
                self.assertEqual(robot.opens, 2)

    def test_robot_never_back(self):
        robot = FakeEndpoint([line("L1", "Downloading", 1), HANG], answers=lambda: False)
        with self.assertRaisesRegex(UserError, "did not answer"):
            self.pull(robot)
        self.assertEqual(robot.opens, 1)

    def test_endpoint_unreachable_at_start_fails_at_once(self):
        robot = FakeEndpoint(requests.exceptions.ConnectionError("connection refused"))
        with self.assertRaises(requests.exceptions.ConnectionError):
            self.pull(robot)
        self.assertEqual(robot.opens, 1)

    def test_endpoint_unreachable_after_a_drop_is_waited_for(self):
        robot = FakeEndpoint(
            [line("L1", "Downloading", 1), requests.exceptions.ChunkedEncodingError()],
            requests.exceptions.ConnectionError("connection refused"),
            [line("L1", "Downloading", 2)] + COMPLETE,
        )
        self.pull(robot)
        self.assertEqual(robot.opens, 3)

    def test_image_not_found_fails_at_once(self):
        robot = FakeEndpoint(NotFound("manifest unknown"))
        with self.assertRaises(NotFound):
            self.pull(robot)
        self.assertEqual(robot.opens, 1)

    def test_stuck_download_gives_up_with_reboot_hint(self):
        robot = FakeEndpoint(
            [line("L1", "Downloading", 1)] + chatter(10 * HEARTBEAT), chatter(10 * HEARTBEAT)
        )
        with self.assertRaisesRegex(UserError, "reboot the robot"):
            self.pull(robot)
        self.assertGreaterEqual(self.elapsed, TIMINGS["PULL_STUCK_TIMEOUT_SECONDS"])
        self.assertGreater(robot.opens, 2)
        self.assertEqual(robot.cuts, 0)

    def test_slow_link_is_never_cut(self):
        # Docker reports about every 512 kB, so on a slow link its lines come further apart than a
        # stall; each re-attached stream first gets the last line again, then the next one
        gap = 3 * HEARTBEAT
        scripts = [[line("L1", "Downloading", 1), gap]]
        scripts += [
            [line("L1", "Downloading", k - 1), gap - 2 * HEARTBEAT, line("L1", "Downloading", k), gap]
            for k in range(2, 6)
        ]
        scripts += [[line("L1", "Downloading", 5)] + COMPLETE]
        robot = FakeEndpoint(*scripts)
        self.pull(robot)
        self.assertEqual(robot.opens, 6)

    def test_replayed_completion_is_not_progress(self):
        # L1 finished, L2 is stuck on the robot: every re-attach replays "Download complete" for L1
        stuck = [line("L1", "Download complete"), line("L2", "Downloading", 5)] + chatter(10 * HEARTBEAT)
        robot = FakeEndpoint(*([stuck] * 20), COMPLETE)
        with self.assertRaisesRegex(UserError, "reboot the robot"):
            self.pull(robot)

    def test_drops_that_made_progress_do_not_use_up_attempts(self):
        drops = [
            [
                line("L1", "Downloading", 2 * k + 1),
                line("L1", "Downloading", 2 * k + 2),
                requests.exceptions.ChunkedEncodingError(),
            ]
            for k in range(6)
        ]
        robot = FakeEndpoint(*drops, [line("L1", "Downloading", 20)] + COMPLETE)
        self.pull(robot)
        self.assertEqual(robot.opens, 7)

    def test_last_attempt_fails_at_once(self):
        robot = FakeEndpoint([requests.exceptions.ChunkedEncodingError()])
        robot.answers = lambda: robot.opens < 5
        with self.assertRaisesRegex(UserError, "after 5 attempts"):
            self.pull(robot)
        self.assertLess(self.elapsed, TIMINGS["PULL_RECONNECT_TIMEOUT_SECONDS"])


class FakeDockerServer:
    """A local socket that answers one pull request the way a test needs."""

    def __init__(self, answer):
        self.answer = answer
        self.server = socket.create_server(("127.0.0.1", 0))
        self.port = self.server.getsockname()[1]
        self.done = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        connection, _ = self.server.accept()
        with connection:
            request = b""
            while b"\r\n\r\n" not in request:
                request += connection.recv(4096)
            try:
                self.answer(connection)
            except OSError:
                pass
            self.done.wait(10)

    def close(self):
        self.done.set()
        self.server.close()


def send_headers(connection):
    connection.sendall(
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n"
    )


def send_line(connection, text):
    data = text.encode() + b"\r\n"
    connection.sendall(b"%x\r\n%s\r\n" % (len(data), data))


class PullStreamSocketTests(unittest.TestCase):
    RESPONSE_TIMEOUT = 0.5

    def setUp(self):
        patcher = patch.object(du, "PULL_RESPONSE_TIMEOUT_SECONDS", self.RESPONSE_TIMEOUT)
        patcher.start()
        self.addCleanup(patcher.stop)

    def open(self, answer):
        server = FakeDockerServer(answer)
        self.addCleanup(server.close)
        client = du.DockerClientOLD(base_url=f"tcp://127.0.0.1:{server.port}", version="1.41")
        self.addCleanup(client.close)
        return du._open_pull_stream(client, "x:y")

    def test_no_answer_to_the_request_times_out(self):
        started = time.monotonic()
        with self.assertRaises(requests.exceptions.ReadTimeout):
            self.open(lambda connection: None)
        self.assertLess(time.monotonic() - started, 3 * self.RESPONSE_TIMEOUT)

    def test_slow_stream_after_the_answer_has_no_read_timeout(self):
        def answer(connection):
            send_headers(connection)
            send_line(connection, '{"status": "Downloading", "id": "L1"}')
            time.sleep(3 * self.RESPONSE_TIMEOUT)
            send_line(connection, '{"status": "Status: Downloaded newer image for x:y"}')
            connection.sendall(b"0\r\n\r\n")

        _, events = self.open(answer)
        self.assertEqual([event["status"] for event in events][-1], "Status: Downloaded newer image for x:y")

    def test_cut_wakes_a_blocked_reader(self):
        response, events = self.open(send_headers)
        ended = threading.Event()

        def read():
            try:
                for _ in events:
                    pass
            except Exception:
                pass
            ended.set()

        threading.Thread(target=read, daemon=True).start()
        time.sleep(0.2)
        self.assertFalse(ended.is_set())
        du._cut_pull_stream(response)
        self.assertTrue(ended.wait(2))


if __name__ == "__main__":
    unittest.main()
