#!/usr/bin/env python3

import argparse
import ctypes
import os
import re
import select
import signal
import sys
import time


K_DA_RETURN_NOT_PERMITTED = -119930872
CLAIM_TIMEOUT_SECONDS = 10
EJECT_TIMEOUT_SECONDS = 10


class DiskMountGuard:
    def __init__(self, device: str, parent_pid: int):
        self._bsd_name = self._normalize_device(device)
        self._parent_pid = parent_pid
        self._core_foundation = ctypes.CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
        self._disk_arbitration = ctypes.CDLL(
            "/System/Library/Frameworks/DiskArbitration.framework/DiskArbitration"
        )
        self._configure_api()
        self._run_loop = self._core_foundation.CFRunLoopGetCurrent()
        self._run_loop_mode = ctypes.c_void_p.in_dll(
            self._core_foundation, "kCFRunLoopDefaultMode"
        )
        self._session = None
        self._disk = None
        self._claimed = False
        self._claim_error = None
        self._claim_finished = False
        self._eject_error = None
        self._eject_finished = False
        self._stop_requested = False
        self._mount_callback = self._make_mount_callback()
        self._claim_callback = self._make_claim_callback()
        self._eject_callback = self._make_eject_callback()

    @staticmethod
    def _normalize_device(device: str) -> str:
        bsd_name = os.path.basename(device)
        if bsd_name.startswith("rdisk"):
            bsd_name = "disk" + bsd_name[len("rdisk") :]
        if not re.fullmatch(r"disk[0-9]+", bsd_name):
            raise ValueError(f"Expected a whole disk device, received {device!r}.")
        return bsd_name

    def _configure_api(self):
        self._core_foundation.CFRunLoopGetCurrent.argtypes = []
        self._core_foundation.CFRunLoopGetCurrent.restype = ctypes.c_void_p
        self._core_foundation.CFRunLoopRunInMode.argtypes = [
            ctypes.c_void_p,
            ctypes.c_double,
            ctypes.c_bool,
        ]
        self._core_foundation.CFRunLoopRunInMode.restype = ctypes.c_int32
        self._core_foundation.CFRelease.argtypes = [ctypes.c_void_p]
        self._core_foundation.CFRelease.restype = None

        self._disk_arbitration.DASessionCreate.argtypes = [ctypes.c_void_p]
        self._disk_arbitration.DASessionCreate.restype = ctypes.c_void_p
        self._disk_arbitration.DASessionScheduleWithRunLoop.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self._disk_arbitration.DASessionScheduleWithRunLoop.restype = None
        self._disk_arbitration.DASessionUnscheduleFromRunLoop.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self._disk_arbitration.DASessionUnscheduleFromRunLoop.restype = None
        self._disk_arbitration.DADiskCreateFromBSDName.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_char_p,
        ]
        self._disk_arbitration.DADiskCreateFromBSDName.restype = ctypes.c_void_p
        self._disk_arbitration.DADiskGetBSDName.argtypes = [ctypes.c_void_p]
        self._disk_arbitration.DADiskGetBSDName.restype = ctypes.c_char_p
        self._disk_arbitration.DADissenterCreate.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int32,
            ctypes.c_void_p,
        ]
        self._disk_arbitration.DADissenterCreate.restype = ctypes.c_void_p
        self._disk_arbitration.DADissenterGetStatus.argtypes = [ctypes.c_void_p]
        self._disk_arbitration.DADissenterGetStatus.restype = ctypes.c_int32

        self._mount_callback_type = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
        self._claim_callback_type = ctypes.CFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
        )
        self._eject_callback_type = ctypes.CFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
        )
        self._disk_arbitration.DARegisterDiskMountApprovalCallback.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            self._mount_callback_type,
            ctypes.c_void_p,
        ]
        self._disk_arbitration.DARegisterDiskMountApprovalCallback.restype = None
        self._disk_arbitration.DADiskClaim.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_void_p,
            self._claim_callback_type,
            ctypes.c_void_p,
        ]
        self._disk_arbitration.DADiskClaim.restype = None
        self._disk_arbitration.DADiskUnclaim.argtypes = [ctypes.c_void_p]
        self._disk_arbitration.DADiskUnclaim.restype = None
        self._disk_arbitration.DADiskEject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            self._eject_callback_type,
            ctypes.c_void_p,
        ]
        self._disk_arbitration.DADiskEject.restype = None

    def _make_mount_callback(self):
        @self._mount_callback_type
        def callback(disk, _):
            bsd_name = self._disk_arbitration.DADiskGetBSDName(disk)
            if not bsd_name:
                return None
            candidate = bsd_name.decode("ascii", errors="ignore")
            if candidate == self._bsd_name or candidate.startswith(f"{self._bsd_name}s"):
                return self._disk_arbitration.DADissenterCreate(
                    None, K_DA_RETURN_NOT_PERMITTED, None
                )
            return None

        return callback

    def _make_claim_callback(self):
        @self._claim_callback_type
        def callback(_, dissenter, __):
            if dissenter:
                status = self._disk_arbitration.DADissenterGetStatus(dissenter)
                self._claim_error = f"Disk Arbitration refused the claim (status {status})."
            else:
                self._claimed = True
            self._claim_finished = True

        return callback

    def _make_eject_callback(self):
        @self._eject_callback_type
        def callback(_, dissenter, __):
            if dissenter:
                status = self._disk_arbitration.DADissenterGetStatus(dissenter)
                self._eject_error = f"Disk Arbitration could not eject the card (status {status})."
            self._eject_finished = True

        return callback

    def _run_loop_once(self, seconds: float):
        self._core_foundation.CFRunLoopRunInMode(
            self._run_loop_mode, seconds, True
        )

    def _wait_for(self, predicate, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while not predicate():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self._run_loop_once(min(remaining, 0.1))
        return True

    def _parent_is_alive(self) -> bool:
        if self._parent_pid <= 0:
            return True
        try:
            os.kill(self._parent_pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _read_command(self):
        readable, _, _ = select.select([sys.stdin], [], [], 0)
        if not readable:
            return None
        command = sys.stdin.readline()
        if not command:
            return "EJECT"
        return command.strip().upper()

    def _claim(self):
        self._session = self._disk_arbitration.DASessionCreate(None)
        if not self._session:
            raise RuntimeError("Could not create a Disk Arbitration session.")
        self._disk_arbitration.DASessionScheduleWithRunLoop(
            self._session, self._run_loop, self._run_loop_mode
        )
        self._disk = self._disk_arbitration.DADiskCreateFromBSDName(
            None, self._session, self._bsd_name.encode("ascii")
        )
        if not self._disk:
            raise RuntimeError(f"Could not open /dev/{self._bsd_name} in Disk Arbitration.")
        self._disk_arbitration.DARegisterDiskMountApprovalCallback(
            self._session, None, self._mount_callback, None
        )
        self._disk_arbitration.DADiskClaim(
            self._disk, 0, None, None, self._claim_callback, None
        )
        if not self._wait_for(lambda: self._claim_finished, CLAIM_TIMEOUT_SECONDS):
            raise RuntimeError("Timed out while claiming the SD card.")
        if self._claim_error:
            raise RuntimeError(self._claim_error)

    def _eject(self) -> bool:
        self._eject_finished = False
        self._eject_error = None
        self._disk_arbitration.DADiskEject(self._disk, 0, self._eject_callback, None)
        if not self._wait_for(lambda: self._eject_finished, EJECT_TIMEOUT_SECONDS):
            self._eject_error = "Timed out while ejecting the SD card."
        return self._eject_error is None

    def _cleanup(self):
        if self._claimed and self._disk:
            self._disk_arbitration.DADiskUnclaim(self._disk)
            self._claimed = False
        if self._session:
            self._disk_arbitration.DASessionUnscheduleFromRunLoop(
                self._session, self._run_loop, self._run_loop_mode
            )
        if self._disk:
            self._core_foundation.CFRelease(self._disk)
            self._disk = None
        if self._session:
            self._core_foundation.CFRelease(self._session)
            self._session = None

    def run(self) -> int:
        try:
            self._claim()
            print("READY", flush=True)
            while not self._stop_requested:
                command = self._read_command()
                if command == "EJECT" or not self._parent_is_alive():
                    self._stop_requested = True
                    break
                self._run_loop_once(0.1)
            if self._eject():
                print("EJECTED", flush=True)
                return 0
            print(f"EJECT_FAILED {self._eject_error}", flush=True)
            return 1
        except Exception as error:
            print(f"ERROR {error}", flush=True)
            return 1
        finally:
            self._cleanup()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", required=True, help="Whole macOS disk device to guard")
    parser.add_argument("--parent-pid", type=int, required=True, help="Parent process to monitor")
    parsed = parser.parse_args()
    if sys.platform != "darwin":
        print("ERROR This helper only runs on macOS.", flush=True)
        return 1
    if os.geteuid() != 0:
        print("ERROR This helper must run as root.", flush=True)
        return 1

    guard = DiskMountGuard(parsed.device, parsed.parent_pid)

    def request_stop(_, __):
        guard._stop_requested = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    return guard.run()


if __name__ == "__main__":
    raise SystemExit(main())
