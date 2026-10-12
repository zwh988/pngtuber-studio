"""Build the HTTP response that serves one file with Range support (M2-S7).

The caller decides which file may be served (the app only ever passes paths
taken from the open project's source list). This module never sees a request
path from the browser.
"""

import mimetypes
from pathlib import Path

from fastapi.responses import JSONResponse, Response, StreamingResponse

from backend.media.ranges import iter_file, parse_range


def range_response(path: Path, range_header: str | None) -> Response:
    """200 with the whole file, 206 for a satisfiable Range, 416 otherwise."""
    try:
        size = path.stat().st_size
    except OSError:
        return JSONResponse({"detail": "footage file not found"}, status_code=404)
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if range_header is None:
        return StreamingResponse(
            iter_file(path, 0, size - 1),
            media_type=mime,
            headers={"Accept-Ranges": "bytes", "Content-Length": str(size)},
        )
    parsed = parse_range(range_header, size)
    if parsed is None:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    start, end = parsed
    return StreamingResponse(
        iter_file(path, start, end),
        status_code=206,
        media_type=mime,
        headers={
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(end - start + 1),
        },
    )
