import contextlib
import shutil
import subprocess
import wave
from pathlib import Path

from app.asr.base import BackendError


def to_wav16k(path: str) -> str:
    """16 kHz mono wav for backends that need it (bhashini, local). Needs ffmpeg."""
    out = str(Path(path).with_suffix(".16k.wav"))
    if not shutil.which("ffmpeg"):
        raise BackendError("ffmpeg not installed; required for this backend")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-ac", "1", "-ar", "16000", out],
        check=True,
    )
    return out


def wav_info(path: str) -> tuple[float | None, int | None]:
    """(duration_seconds, sample_rate) for wav uploads; (None, None) otherwise."""
    # ponytail: stdlib wave only; use ffprobe for mp3/webm when metadata matters
    with contextlib.suppress(Exception), wave.open(path) as w:
        return w.getnframes() / w.getframerate(), w.getframerate()
    return None, None
