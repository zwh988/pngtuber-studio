"""M0-3 spike: FastAPI Range-request video endpoint inside a pywebview window. Throwaway."""
import argparse
import mimetypes
import re
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import uvicorn
import webview
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse

HOST = "127.0.0.1"
PORT = 8765
CHUNK = 1024 * 1024

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Player spike</title>
<style>
  body { font-family: sans-serif; background: #1b1b1f; color: #ddd; margin: 12px; }
  video { width: 100%; max-height: 65vh; background: #000; }
  button { margin: 6px 6px 6px 0; padding: 6px 10px; }
  #log { font-family: monospace; font-size: 12px; white-space: pre-wrap; height: 22vh; overflow-y: auto;
         background: #111; padding: 6px; }
</style></head><body>
<video id="v" src="/video" controls preload="metadata"></video>
<div>
  <button onclick="seekFrac(0)">0%</button>
  <button onclick="seekFrac(0.25)">25%</button>
  <button onclick="seekFrac(0.5)">50%</button>
  <button onclick="seekFrac(0.75)">75%</button>
  <button onclick="seekEnd()">end - 0.5 s</button>
  <button onclick="seekBy(-5)">-5 s</button>
  <button onclick="seekBy(5)">+5 s</button>
  <button onclick="v.play()">play</button>
  <button onclick="v.pause()">pause</button>
</div>
<div id="log"></div>
<script>
  const v = document.getElementById("v");
  const logEl = document.getElementById("log");
  let seekStart = 0;
  function log(msg) {
    logEl.textContent += msg + "\\n";
    logEl.scrollTop = logEl.scrollHeight;
  }
  function seekTo(t) {
    seekStart = performance.now();
    log("seek requested -> " + t.toFixed(2) + " s");
    v.currentTime = t;
  }
  function seekFrac(f) { seekTo(v.duration * f); }
  function seekEnd() { seekTo(Math.max(v.duration - 0.5, 0)); }
  function seekBy(d) { seekTo(Math.min(Math.max(v.currentTime + d, 0), v.duration)); }
  v.addEventListener("loadedmetadata", () =>
    log("metadata: " + v.duration.toFixed(2) + " s, " + v.videoWidth + "x" + v.videoHeight));
  v.addEventListener("seeked", () =>
    log("seeked at " + v.currentTime.toFixed(2) + " s after " + (performance.now() - seekStart).toFixed(0) + " ms"));
  v.addEventListener("waiting", () => log("waiting (buffering)"));
  v.addEventListener("stalled", () => log("stalled"));
  v.addEventListener("ended", () => log("ended"));
  v.addEventListener("error", () =>
    log("ERROR code=" + (v.error ? v.error.code : "?") + " msg=" + (v.error ? v.error.message : "")));
</script></body></html>
"""


def parse_range(header: str, size: int) -> tuple[int, int] | None:
    """Parse a single 'bytes=a-b' range into inclusive (start, end), or None if unsatisfiable."""
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
    if match is None:
        return None
    start_s, end_s = match.groups()
    if start_s == "" and end_s == "":
        return None
    if start_s == "":
        suffix = int(end_s)
        if suffix == 0:
            return None
        start, end = max(size - suffix, 0), size - 1
    else:
        start = int(start_s)
        end = min(int(end_s), size - 1) if end_s else size - 1
    if start > end or start >= size:
        return None
    return start, end


def iter_file(path: Path, start: int, end: int) -> Iterator[bytes]:
    with path.open("rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            data = f.read(min(CHUNK, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


def build_app(video: Path) -> FastAPI:
    app = FastAPI()
    size = video.stat().st_size
    mime = mimetypes.guess_type(video.name)[0] or "application/octet-stream"

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return PAGE

    @app.get("/video")
    def get_video(request: Request) -> Response:
        range_header = request.headers.get("range")
        if range_header is None:
            print("GET /video (no Range) -> 200 full file", flush=True)
            return StreamingResponse(
                iter_file(video, 0, size - 1),
                media_type=mime,
                headers={"Accept-Ranges": "bytes", "Content-Length": str(size)},
            )
        rng = parse_range(range_header, size)
        if rng is None:
            print(f"GET /video Range={range_header} -> 416", flush=True)
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        start, end = rng
        print(f"GET /video Range={range_header} -> 206 {start}-{end}/{size}", flush=True)
        return StreamingResponse(
            iter_file(video, start, end),
            status_code=206,
            media_type=mime,
            headers={
                "Content-Range": f"bytes {start}-{end}/{size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(end - start + 1),
            },
        )

    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True, help="path to a local test video")
    args = parser.parse_args()

    video = Path(args.video)
    if not video.is_file():
        raise SystemExit(f"Video not found: {video}")

    server = uvicorn.Server(uvicorn.Config(build_app(video), host=HOST, port=PORT, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)

    webview.create_window("Player spike", f"http://{HOST}:{PORT}/", width=1100, height=800)
    webview.start()
    server.should_exit = True


if __name__ == "__main__":
    main()