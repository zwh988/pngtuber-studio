# Third-party notices

PNGtuber Studio is licensed under the GNU General Public License v3.0 or later (see `LICENSE`). Pedalboard, which it links to, is GPL-3.0, so the whole app is distributed under the GPL.

This repository contains only PNGtuber Studio's own code. The components below are **not included in the repository**: `install.bat` downloads them onto the user's machine from their official sources, and each one stays under its own licence.

## Downloaded by `install.bat`

| Component | Version | Licence | Source |
|---|---|---|---|
| FFmpeg (BtbN build, `win64-gpl-8.1`) | n8.1.3-27-g8dca1586f4 | GPL-3.0 (GPL build, with libx264 and others); its licence is copied to `bin\ffmpeg-LICENSE.txt` | https://github.com/BtbN/FFmpeg-Builds, source code at https://ffmpeg.org |
| uv | 0.13.0 | MIT or Apache-2.0 | https://github.com/astral-sh/uv |
| Node.js (build only, not used at runtime) | 24.21.0 | MIT, plus the licences in `tools\node\LICENSE` | https://nodejs.org |
| Python 3.11 (fetched by uv) | 3.11 | PSF License | https://www.python.org |

## Downloaded by the app on first run

| Component | Licence | Source |
|---|---|---|
| Chatterbox voice model weights (Resemble AI) | MIT | https://huggingface.co/ResembleAI/chatterbox |

## Python packages (installed by `uv sync`, pinned in `uv.lock`)

Main packages the app uses directly. Their dependencies are listed in `uv.lock`, and each one's licence is in `.venv\Lib\site-packages\<package>-<version>.dist-info\`.

| Package | Licence |
|---|---|
| chatterbox-tts (Resemble AI) | MIT |
| resemble-perth (watermarker used by Chatterbox) | MIT |
| Pedalboard (Spotify) | GPL-3.0 |
| PyTorch, torchaudio | BSD-3-Clause |
| transformers, diffusers, huggingface-hub, safetensors | Apache-2.0 |
| FastAPI, pydantic, pyloudnorm | MIT |
| uvicorn, pywebview, soundfile, NumPy | BSD-3-Clause |
| Pillow | MIT-CMU |
| librosa | ISC |

## Frontend (bundled into `frontend\dist` by the build)

| Package | Licence |
|---|---|
| Svelte, Vite | MIT |
| Lucide icons (`@lucide/svelte` 1.66.0) | ISC |

The full list is in `frontend\package-lock.json`, and each package's licence is in `frontend\node_modules\<package>\`.

## Voice cloning

The voice model clones the voice in the reference clip you give it. Use only your own voice, or a voice whose owner has given you permission. Chatterbox adds an inaudible watermark (Resemble AI's Perth) to everything it generates.
