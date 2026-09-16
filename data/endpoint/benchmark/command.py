import os
import signal
import tempfile
import time

from dt_data_api import TransferStatus
from dt_shell import DTCommandAbs, dtslogger

from utils.data_endpoint_utils import create_data_client, get_storage_endpoint
from utils.misc_utils import human_size, human_time
from utils.progress_bar import ProgressBar


TMP_WORKDIR = "/tmp/duckietown/dts/data/endpoint/benchmark"


class DTCommand(DTCommandAbs):
    help = "Benchmarks an object download from a Duckietown Cloud Storage space"

    @staticmethod
    def command(shell, args, **kwargs):
        parsed = DTCommand._resolve_parsed(args, kwargs.get("parsed"))
        object_path = parsed.object.lstrip("/")
        endpoint = get_storage_endpoint(shell, parsed.space)
        token = shell.profile.secrets.dt_token
        storage = create_data_client(shell, token).storage(parsed.space)
        os.makedirs(TMP_WORKDIR, exist_ok=True)

        dtslogger.info(
            f"Benchmarking the '{endpoint}' endpoint for [{parsed.space}]:{object_path}"
        )
        total_downloaded = 0
        total_elapsed = 0.0

        for run_number in range(1, parsed.runs + 1):
            with tempfile.TemporaryDirectory(prefix="download-", dir=TMP_WORKDIR) as temporary_dir:
                destination = os.path.join(temporary_dir, "object.download")
                started_at = time.monotonic()
                handler = storage.download(object_path, destination)
                pbar = ProgressBar(
                    header=f"Run {run_number}/{parsed.runs} downloading [ETA: ND]"
                )

                def update_progress(transfer):
                    percentage = transfer.progress.percentage
                    if percentage > 0:
                        elapsed = time.monotonic() - started_at
                        eta = (100 - percentage) * (elapsed / percentage)
                        pbar.set_header(
                            f"Run {run_number}/{parsed.runs} downloading "
                            f"[ETA: {human_time(eta, compact=True)}]"
                        )
                    pbar.update(percentage)

                handler.register_callback(update_progress)
                update_progress(handler)
                signal.signal(signal.SIGINT, lambda *_: handler.abort())
                handler.join()
                elapsed = time.monotonic() - started_at

                if handler.status == TransferStatus.STOPPED:
                    print()
                    dtslogger.error("Benchmark stopped before the download completed.")
                    exit(1)
                if handler.status == TransferStatus.ERROR:
                    print()
                    dtslogger.error(handler.reason)
                    exit(1)
                if handler.progress.transferred != handler.progress.total:
                    print()
                    dtslogger.error("Benchmark download did not complete.")
                    exit(1)

                pbar.done()
                total_downloaded += handler.progress.transferred
                total_elapsed += elapsed
                if parsed.runs > 1:
                    run_speed = handler.progress.transferred / elapsed if elapsed else 0
                    print(
                        f"Run {run_number}/{parsed.runs}: "
                        f"{human_size(handler.progress.transferred)} in {elapsed:.2f}s "
                        f"({human_size(run_speed)}/s)"
                    )

        average_speed = total_downloaded / total_elapsed if total_elapsed else 0
        print(f"Storage space: {parsed.space}")
        print(f"Endpoint: {endpoint}")
        print(f"Runs: {parsed.runs}")
        if parsed.runs == 1:
            print(f"Downloaded: {human_size(total_downloaded)}")
            print(f"Elapsed: {total_elapsed:.2f}s")
        else:
            print(f"Total downloaded: {human_size(total_downloaded)}")
            print(f"Total elapsed: {total_elapsed:.2f}s")
        print(f"Average speed: {human_size(average_speed)}/s")
