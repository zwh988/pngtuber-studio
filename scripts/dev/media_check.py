"""M2-S7 manual check: play a project's footage through /media/source/{id}.

Opens the project in a pywebview window with a plain <video> tag pointed at the
real media endpoint, plus seek buttons that log how long each seek takes. The
terminal prints every request with its status (expect 206 for seeks).
Throwaway dev tool; not part of the app.

    uv run python scripts\\dev\\media_check.py --project "<project folder>"
"""

import argparse
import sys
import tempfile
import threading
import time
from pathlib import Path

PORT = 8766

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Media check</title>
<style>
  body { font-family: sans-serif; background: #1b1b1f; color: #ddd; margin: 12px; }
  video { width: 100%; max-height: 62vh; background: #000; }
  button { margin: 6px 6px 6px 0; padding: 6px 10px; }
  #log { font-family: monospace; font-size: 12px; white-space: pre-wrap; height: 22vh;
         overflow-y: auto; background: #111; padding: 6px; }
</style></head><body>
<div>SOURCE_LABEL</div>
<video id="v" src="SOURCE_URL" controls preload="metadata"></video>
<div>
  <button onclick="seekFrac(0)">0%</button>
  <button onclick="seekFrac(0.25)">25%</button>
  <button onclick="seekFrac(0.5)">50%</button>
  <button onclick="seekFrac(0.75)">75%</button>
  <button onclick="seekTo(Math.max(v.duration - 0.5, 0))">end - 0.5 s</button>
  <button onclick="seekTo(Math.max(v.currentTime - 5, 0))">-5 s</button>
  <button onclick="seekTo(Math.min(v.currentTime + 5, v.duration))">+5 s</button>
  <button onclick="v.play()">play</button>
  <button onclick="v.pause()">pause</button>
</div>
<div id="log"></div>
<script>
  const v = document.getElementById("v");
  const logEl = document.getElementById("log");
  let t0 = 0;
  function log(m) { logEl.textContent += m + "\\n"; logEl.scrollTop = logEl.scrollHeight; }
  function seekTo(t) { t0 = performance.now(); log("seek -> " + t.toFixed(2) + " s"); v.currentTime = t; }
  function seekFrac(f) { seekTo(v.duration * f); }
  v.addEventListener("loadedmetadata", () =>
    log("metadata: " + v.duration.toFixed(2) + " s, " + v.videoWidth + "x" + v.videoHeight));
  v.addEventListener("seeked", () =>
    log("seeked at " + v.currentTime.toFixed(2) + " s after " + (performance.now() - t0).toFixed(0) + " ms"));
  v.addEventListener("waiting", () => log("waiting (buffering)"));
  v.addEventListener("error", () =>
    log("ERROR code=" + (v.error ? v.error.code : "?") + " " + (v.error ? v.error.message : "")));
</script></body></html>
"""


def main() -> None:
    # Run from anywhere: put the repo root on the path so `backend` imports.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

    import uvicorn
    import webview
    from fastapi.responses import HTMLResponse

    from backend.app import create_app
    from backend.project.session import Session

    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, help="a project folder (has project.json)")
    parser.add_argument("--source", help="source id; default: the first source whose file exists")
    args = parser.parse_args()

    session = Session()
    session.open_project(args.project)
    items = [i for i in session.footage().items if i.exists]
    if args.source:
        items = [i for i in items if i.id == args.source]
    if not items:
        raise SystemExit("no source with an existing file in that project")
    item = items[0]
    page = PAGE.replace("SOURCE_URL", f"/media/source/{item.id}").replace(
        "SOURCE_LABEL", f"{item.path} ({item.width}x{item.height}, {item.duration_ms} ms)"
    )

    # An empty static dir keeps the built frontend out of the way of /check.
    app = create_app(static_dir=Path(tempfile.mkdtemp()), session=session)

    @app.get("/check", response_class=HTMLResponse)
    def check() -> str:
        return page

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="info"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)

    webview.create_window("Media check", f"http://127.0.0.1:{PORT}/check", width=1100, height=800)
    webview.start()
    server.should_exit = True


if __name__ == "__main__":
    main()
