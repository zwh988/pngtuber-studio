"""Files dropped from Explorer onto the window (M8-1). Pure.

pywebview's Python ``drop`` handler receives the page's drop event with each
file's full path in ``pywebviewFullPath`` (WebView2 only; see the drop spike in
``scripts/spike/drop_spike.py``). The shell turns that event into a small
message and hands it to the page, which knows what lies under the drop point.
"""

import json
from typing import Any

# The page function the shell calls with the message (set by Editor.svelte).
PAGE_CALLBACK = "__pngtuberFilesDropped"


def dropped_files(event: dict[str, Any]) -> dict[str, Any] | None:
    """``{"x", "y", "paths"}`` for a drop of files, else None (a drag inside the
    page, such as a line from the bank, has no files)."""
    transfer = event.get("dataTransfer")
    files = transfer.get("files") if isinstance(transfer, dict) else None
    if not isinstance(files, list):
        return None
    paths = [
        f["pywebviewFullPath"]
        for f in files
        if isinstance(f, dict) and isinstance(f.get("pywebviewFullPath"), str)
    ]
    if not paths:
        return None
    x, y = event.get("clientX"), event.get("clientY")
    if not isinstance(x, int | float) or not isinstance(y, int | float):
        return None
    return {"x": x, "y": y, "paths": paths}


def page_call(message: dict[str, Any]) -> str:
    """JavaScript that passes ``message`` to the page callback, if the page has one."""
    payload = json.dumps(message)
    return f"window.{PAGE_CALLBACK} && window.{PAGE_CALLBACK}({payload})"
