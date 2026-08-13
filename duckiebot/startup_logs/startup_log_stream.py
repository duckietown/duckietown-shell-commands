import argparse
import os
import time


def _parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--startup-started-at", type=int, required=True)
    parser.add_argument("--poll-interval", type=float, required=True)
    parser.add_argument("--completion-marker", type=str, action="append", required=True)
    parser.add_argument("log_files", nargs="+")
    return parser.parse_args()


def _log_was_updated(path, startup_started_at):
    try:
        return int(os.stat(path).st_mtime) >= startup_started_at
    except FileNotFoundError:
        return False


def _stream_startup_logs(log_files, startup_started_at, poll_interval, completion_markers):
    offsets = {path: 0 for path in log_files}
    pending_fragments = {path: "" for path in log_files}
    active_log_files = set()
    completion_markers_set = set(completion_markers)
    stop_stream = False
    while not stop_stream:
        for path in log_files:
            if path not in active_log_files:
                if not _log_was_updated(path, startup_started_at):
                    continue
                active_log_files.add(path)
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fin:
                    fin.seek(offsets[path])
                    chunk = fin.read()
                    offsets[path] = fin.tell()
            except FileNotFoundError:
                continue
            if not chunk:
                continue
            lines = (pending_fragments[path] + chunk).replace("\r", "\n").split("\n")
            pending_fragments[path] = lines.pop()
            for line in lines:
                if not line.strip():
                    continue
                message = line.rstrip()
                print(message, flush=True)
                if message in completion_markers_set:
                    stop_stream = True
                    break
            if stop_stream:
                break
        time.sleep(poll_interval)
    for pending_fragment in pending_fragments.values():
        if not pending_fragment.strip():
            continue
        message = pending_fragment.rstrip()
        print(message, flush=True)
        if message in completion_markers_set:
            break


def main():
    args = _parse_args()
    _stream_startup_logs(
        log_files=args.log_files,
        startup_started_at=args.startup_started_at,
        poll_interval=args.poll_interval,
        completion_markers=args.completion_marker,
    )


if __name__ == "__main__":
    main()
