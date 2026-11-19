"""M8-1 spike: drop files from Explorer onto a pywebview window and get their full paths in Python.

Run from the repo root:  uv run python scripts\\spike\\drop_spike.py
Drag one or more files (try a path with spaces) onto the window. Python prints each full path
and the drop point; the page shows what Python sent back. Throwaway.
"""

import json
import threading

import webview
from webview.dom import DOMEventHandler

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Drop spike</title>
<style>
  body { font-family: sans-serif; background: #1b1b1f; color: #ddd; margin: 12px; }
  #zone { height: 45vh; border: 2px dashed #666; display: flex; align-items: center;
          justify-content: center; font-size: 18px; }
  #zone.over { border-color: #6cf; background: #223; }
  #log { font-family: monospace; font-size: 12px; white-space: pre-wrap; height: 40vh;
         overflow-y: auto; background: #111; padding: 6px; margin-top: 10px; }
</style></head><body>
<div id="zone">Drop audio files here (Explorer)</div>
<div id="log"></div>
<script>
  const zone = document.getElementById('zone');
  const log = (s) => { const el = document.getElementById('log'); el.textContent += s + '\\n'; };
  // The page must cancel dragover, or the browser refuses the drop.
  document.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('over'); });
  document.addEventListener('dragleave', () => zone.classList.remove('over'));
  document.addEventListener('drop', (e) => {
    zone.classList.remove('over');
    const names = Array.from(e.dataTransfer.files).map((f) => f.name + ' (' + f.size + ' bytes)');
    log('page drop at ' + e.clientX + ',' + e.clientY + ': ' + names.join(', '));
  });
  // Python calls this back with the full paths.
  window.onDroppedPaths = (info) => log('python says: ' + JSON.stringify(info));
</script></body></html>"""


def on_drop(event: dict) -> None:
    files = event.get("dataTransfer", {}).get("files", [])
    paths = [f.get("pywebviewFullPath") for f in files]
    info = {
        "x": event.get("clientX"),
        "y": event.get("clientY"),
        "paths": paths,
        "names": [f.get("name") for f in files],
        "thread": threading.current_thread().name,
    }
    print("DROP", json.dumps(info, ensure_ascii=False), flush=True)
    webview.windows[0].evaluate_js(f"window.onDroppedPaths({json.dumps(info)})")


def on_loaded(window: webview.Window) -> None:
    # prevent_default=True keeps WebView2 from opening the file; stop_propagation=False lets the
    # page's own drop listener run too (it knows where the drop landed).
    window.dom.document.events.drop += DOMEventHandler(on_drop, True, False)
    print("drop handler registered; drag files onto the window", flush=True)


if __name__ == "__main__":
    window = webview.create_window("Drop spike", html=PAGE, width=900, height=700)
    window.events.loaded += lambda: on_loaded(window)
    webview.start(gui="edgechromium")
