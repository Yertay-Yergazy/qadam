"""faster-whisper's audio decoding against the installed PyAV (no model download).

PyAV 19 broke faster-whisper 1.2.1 (`av.open(..., metadata_errors=...)`): every transcription failed while all other
tests stayed green. This test decodes a real file through the same code path as production.
"""
import math
import struct
import wave

from faster_whisper.audio import decode_audio


def test_faster_whisper_can_decode_audio_with_installed_pyav(tmp_path):
    path = tmp_path / "tone.wav"
    rate = 16000
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(rate)))

    samples = decode_audio(str(path), sampling_rate=rate)
    assert abs(len(samples) - rate) < rate * 0.01  # one second of audio
