"""Run one crawl job in its own OS process.

    python crawler.py <spec.json>

webapp.py launches this for every dashboard/auto-crawl job (unless
CRAWL_IN_PROCESS=1) so HTML parsing, dedupe, scoring and erf/GV resolution
do not share the web process's GIL with dashboard requests. The contract
with the parent is deliberately small:

- spec.json: {"suburbs", "sources", "pages", "use_ai", "listing_types",
  "only_stale", "progress_path", "skip_pairs"}. skip_pairs is optional:
  [[source, suburb_slug]] the scheduler's idle skipping leaves out.
- stdout: one bare log line per message (the parent timestamps each line,
  appends it to job["log"] and prints it, so `railway logs` still shows it).
- progress_path: a JSON snapshot rewritten atomically every 0.5 s,
  {"pid", "phase", "done", "total", "stored", "per_source", "updated"}; the
  last write carries phase "done", "stopped" or "error".
- SIGTERM/SIGINT: finish the requests in flight and stop (the dashboard's
  Stop button). If the parent dies, the child stops itself, and hard-exits
  30 s later if the pipeline has not returned.
- exit code: 0 finished, 2 stopped via signal, 1 exception.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
import traceback
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pipeline  # noqa: E402

PARENT_GONE_GRACE_S = 30.0


def _log(msg) -> None:
    print(str(msg), flush=True)


def _write_progress(path: str, progress: pipeline.Progress,
                    phase: str) -> None:
    snap = progress.snapshot()
    body = {"pid": os.getpid(), "phase": phase, "done": snap["done"],
            "total": snap["total"], "stored": snap["stored"],
            "per_source": snap["per_source"],
            "updated": datetime.now().isoformat()}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(body, f)
    os.replace(tmp, path)


def main(spec_path: str) -> int:
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    listing_types = tuple(spec.get("listing_types") or ("sale",))
    progress_path = spec["progress_path"]
    phase = ("crawling portals" if listing_types == ("sale",)
             else f"crawling portals ({'+'.join(listing_types)})")

    stop = threading.Event()
    signalled = threading.Event()

    def on_signal(signum, _frame):
        signalled.set()
        stop.set()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    progress = pipeline.Progress()
    finished = threading.Event()
    state = {"phase": phase}
    parent = os.getppid()

    def reporter():
        orphaned_at = None
        while not finished.is_set():
            try:
                _write_progress(progress_path, progress, state["phase"])
            except OSError as e:
                _log(f"crawler: progress write failed: {e}")
            if orphaned_at is None and os.getppid() != parent:
                orphaned_at = time.monotonic()
                _log("crawler: parent process gone — stopping")
                stop.set()
            if orphaned_at is not None and \
                    time.monotonic() - orphaned_at > PARENT_GONE_GRACE_S:
                os._exit(3)
            finished.wait(0.5)

    threading.Thread(target=reporter, daemon=True).start()

    rc = 0
    try:
        pipeline.run(spec["suburbs"], spec["sources"],
                     pages=int(spec.get("pages", 1)),
                     use_ai=bool(spec.get("use_ai", True)),
                     log=_log, progress=progress, stop=stop,
                     only_stale=bool(spec.get("only_stale", True)),
                     listing_types=listing_types,
                     skip_pairs=[tuple(p) for p in
                                 spec.get("skip_pairs") or []])
        if signalled.is_set():
            state["phase"], rc = "stopped", 2
        else:
            state["phase"], rc = "done", 0
    except BaseException as e:                          # noqa: BLE001
        for line in traceback.format_exc().rstrip().splitlines():
            _log(line)
        _log(f"ERROR: {type(e).__name__}: {e}")
        state["phase"], rc = "error", 1
    finally:
        finished.set()
        try:
            _write_progress(progress_path, progress, state["phase"])
        except OSError as e:
            _log(f"crawler: final progress write failed: {e}")
    return rc


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python crawler.py <spec.json>")
    sys.exit(main(sys.argv[1]))
