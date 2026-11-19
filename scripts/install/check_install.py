"""Post-install checks (M7 S2): CUDA torch, the GPU, ffmpeg with NVENC, ffprobe.

Run from the repo root: ``uv run python scripts\\install\\check_install.py``
Prints one line per check and exits 1 when a check that the app needs fails.
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

MIN_VRAM_GIB = 6.0


def _line(status: str, name: str, detail: str) -> None:
    print(f"  [{status}] {name}: {detail}")


def check_torch() -> bool:
    try:
        import torch
    except Exception as exc:  # noqa: BLE001 - any import failure is reported as is
        _line("FAIL", "torch", f"could not be imported: {exc}")
        return False
    _line("OK", "torch", f"{torch.__version__} (built for CUDA {torch.version.cuda})")
    if not torch.cuda.is_available():
        _line(
            "FAIL",
            "CUDA",
            "not available. Install or update the NVIDIA driver (570 or newer), "
            "restart Windows, then run install.bat again.",
        )
        return False
    props = torch.cuda.get_device_properties(0)
    vram = props.total_memory / 1024**3
    status = "OK" if vram >= MIN_VRAM_GIB else "WARN"
    note = (
        ""
        if vram >= MIN_VRAM_GIB
        else f" (under {MIN_VRAM_GIB:.0f} GiB: voice generation may run out of memory)"
    )
    _line(status, "GPU", f"{props.name}, {vram:.1f} GiB VRAM{note}")
    return True


def check_ffmpeg() -> bool:
    from backend.export.tools import default_ffmpeg_path, encoder_problem

    problem = encoder_problem(default_ffmpeg_path(), refresh=True)
    if problem is not None:
        _line("FAIL", "ffmpeg NVENC", problem)
        return False
    _line("OK", "ffmpeg NVENC", f"h264_nvenc opens ({default_ffmpeg_path()})")
    return True


def check_ffprobe() -> bool:
    from backend.project.footage import default_ffprobe_path

    path = default_ffprobe_path()
    if not path.is_file():
        _line("FAIL", "ffprobe", f"not found at {path}")
        return False
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        result = subprocess.run(
            [str(path), "-hide_banner", "-version"],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=flags,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _line("FAIL", "ffprobe", f"could not be run: {exc}")
        return False
    first = result.stdout.splitlines()[0] if result.stdout else "no output"
    if result.returncode != 0:
        _line("FAIL", "ffprobe", first)
        return False
    _line("OK", "ffprobe", first)
    return True


def main() -> int:
    results = [check_torch(), check_ffmpeg(), check_ffprobe()]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
