"""PCM capture storage and lossless/MP3 export. No device or GUI dependencies."""
from __future__ import annotations

from array import array
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import wave

FORMATS = {"wav": "WAV · PCM sin comprimir", "flac": "FLAC · sin pérdida", "mp3": "MP3 · alta calidad"}
# Leave room for RIFF headers; stop cleanly before the 32-bit WAV size limit.
MAX_PCM_BYTES = 4_000_000_000


def pcm16(data: bytes, gain_db: float = 0.):
    """Return little-endian PCM, post-gain peak/RMS and source/output clipping."""
    if len(data) % 2:
        raise ValueError("Bloque PCM incompleto")
    samples = array('h'); samples.frombytes(data)
    if sys.byteorder != 'little': samples.byteswap()
    multiplier = 10 ** (max(-24., min(24., gain_db)) / 20.)
    peak, squares, clipped = 0, 0., False
    for i, sample in enumerate(samples):
        value = round(sample * multiplier)
        clipped = clipped or abs(sample) >= 32767 or value > 32767 or value < -32768
        value = max(-32768, min(32767, value))
        samples[i] = value
        peak = max(peak, abs(value)); squares += value * value
    rms = math.sqrt(squares / len(samples)) / 32768 if samples else 0.
    if sys.byteorder != 'little': samples.byteswap()
    return samples.tobytes(), peak / 32768, rms, clipped


def dbfs(amplitude):
    return max(-60., 20 * math.log10(max(amplitude, 0.001)))


class WaveTake:
    """Stream PCM to a private recovery WAV with a continuously updated header."""
    def __init__(self, directory, rate, channels):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(prefix="toma-", suffix=".wav", dir=self.directory)
        self.path = Path(name)
        self.stream = os.fdopen(fd, 'w+b')
        try:
            self.writer = wave.open(self.stream, 'wb')
            self.writer.setparams((channels, 2, rate, 0, 'NONE', 'not compressed'))
            self.writer.writeframes(b''); self.stream.flush()
        except Exception:
            try:
                self.writer.close()
            except Exception:
                pass
            self.stream.close(); self.path.unlink(missing_ok=True)
            raise
        self.rate, self.channels, self.frames = rate, channels, 0
        self.closed = False

    @property
    def duration(self):
        return self.frames / self.rate

    def append(self, data):
        if self.closed: raise ValueError("La toma ya está cerrada")
        if len(data) % (2 * self.channels): raise ValueError("Fotograma PCM incompleto")
        if self.frames * 2 * self.channels + len(data) > MAX_PCM_BYTES:
            raise OSError("Se ha alcanzado el límite de 4 GB de la toma WAV. Guarda esta toma y comienza otra.")
        # writeframes patches the WAV header every block, so a crashed session
        # leaves an ordinary readable WAV, not a raw file with a stale header.
        self.writer.writeframes(data)
        self.stream.flush()
        self.frames += len(data) // (2 * self.channels)

    def finish(self):
        if not self.closed:
            self.closed = True
            try:
                self.writer.close()
                self.stream.flush()
                os.fsync(self.stream.fileno())
            finally:
                self.stream.close()

    def discard(self):
        self.finish(); self.path.unlink(missing_ok=True)


class ExportCancelled(Exception):
    pass


def export_audio(source, destination, kind, cancelled=None, progress=None):
    """Atomic export. An error/cancel never replaces an existing destination."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if kind not in FORMATS: raise ValueError("Formato de audio no admitido")
    if source == destination: raise ValueError("Elige un archivo distinto de la copia de recuperación")
    cancel = cancelled or threading.Event()
    temporary = None
    process = None
    try:
        fd, name = tempfile.mkstemp(prefix='.atril-export-', suffix='.' + kind, dir=destination.parent)
        temporary = Path(name)
        os.close(fd)
        if kind == 'wav':
            total, done = source.stat().st_size, 0
            with source.open('rb') as incoming, temporary.open('wb') as outgoing:
                while True:
                    if cancel.is_set(): raise ExportCancelled()
                    block = incoming.read(1024 * 1024)
                    if not block: break
                    outgoing.write(block); done += len(block)
                    if progress: progress(min(99, round(done * 100 / max(1, total))))
        else:
            executable = shutil.which('ffmpeg')
            if not executable:
                raise RuntimeError("No se encuentra FFmpeg. Puedes guardar en WAV o instalar FFmpeg para usar FLAC y MP3.")
            codec = ['-c:a', 'flac', '-compression_level', '5'] if kind == 'flac' else ['-c:a', 'libmp3lame', '-q:a', '2']
            process = subprocess.Popen([executable, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                '-i', str(source), '-map', '0:a:0', '-map_metadata', '-1', *codec, '-f', kind, str(temporary)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            while True:
                if cancel.is_set():
                    process.kill(); process.communicate(); raise ExportCancelled()
                try:
                    _, errors = process.communicate(timeout=.15); break
                except subprocess.TimeoutExpired:
                    pass
            if process.returncode:
                raise RuntimeError("FFmpeg no pudo guardar la grabación. La toma se conserva.\n" + errors.decode(errors='replace')[-1600:])
        if cancel.is_set(): raise ExportCancelled()
        if not temporary.stat().st_size: raise RuntimeError("El archivo exportado está vacío")
        with temporary.open('rb') as result: os.fsync(result.fileno())
        os.replace(temporary, destination)
        if progress: progress(100)
        return destination
    finally:
        if process is not None and process.poll() is None:
            process.kill(); process.communicate()
        if temporary is not None: temporary.unlink(missing_ok=True)
