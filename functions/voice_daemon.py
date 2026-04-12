#!/usr/bin/env python3
"""
voice_daemon.py -- ASHI always-on voice interface.

Listens for wake word ("hey ashi" or "alexa" placeholder), records speech,
transcribes via faster-whisper, dispatches to ASHI daemon, speaks response via piper.

100% local. No cloud APIs.

Requires: openwakeword, faster-whisper, sounddevice, webrtcvad, piper-tts (or piper binary)
"""

# ---------------------------------------------------------------------------
# PATH FIX: same as ashi_daemon.py — avoid functions/secrets.py shadowing stdlib
# ---------------------------------------------------------------------------
import os
import sys

_FUNCTIONS_DIR = os.path.dirname(os.path.abspath(__file__))
if sys.path and os.path.abspath(sys.path[0]) == _FUNCTIONS_DIR:
    sys.path.pop(0)
    if _FUNCTIONS_DIR not in sys.path:
        sys.path.append(_FUNCTIONS_DIR)
elif _FUNCTIONS_DIR not in sys.path:
    sys.path.append(_FUNCTIONS_DIR)

import io
import logging
import shutil
import signal
import struct
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import httpx
import numpy as np
import sounddevice as sd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ASHI_DAEMON_URL = os.getenv("ASHI_DAEMON_URL", "http://127.0.0.1:7070")
WAKE_WORD_MODEL = os.getenv("ASHI_WAKE_WORD", "alexa")  # "hey_ashi" when custom model ready
SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"
FRAME_DURATION_MS = 30  # webrtcvad frame size: 10, 20, or 30 ms
FRAME_SIZE = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)  # 480 samples
SILENCE_TIMEOUT_S = 1.5  # stop recording after this much silence
MAX_RECORD_S = 30  # hard cap on recording length
VAD_AGGRESSIVENESS = 2  # 0-3, higher = more aggressive filtering
POLL_INTERVAL_S = 2.0
POLL_TIMEOUT_S = 300.0  # 5 min max wait for agent
WHISPER_MODEL = os.getenv("ASHI_WHISPER_MODEL", "base.en")
PIPER_VOICE_DIR = Path.home() / ".local" / "share" / "piper"
PIPER_VOICE = os.getenv(
    "ASHI_PIPER_VOICE",
    str(PIPER_VOICE_DIR / "en_US-lessac-medium.onnx"),
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR = Path.home() / "SecondBrain" / "AI" / "agent-logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("ashi_voice")
logger.setLevel(logging.INFO)

_fh = logging.FileHandler(LOG_DIR / "voice.log")
_fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(_fh)

_ch = logging.StreamHandler()
_ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(_ch)


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

def generate_beep(freq: int = 880, duration_ms: int = 150, volume: float = 0.3) -> np.ndarray:
    """Generate a short beep tone as int16 numpy array. No external files needed."""
    n_samples = int(SAMPLE_RATE * duration_ms / 1000)
    t = np.linspace(0, duration_ms / 1000, n_samples, endpoint=False)
    tone = (volume * 32767 * np.sin(2 * np.pi * freq * t)).astype(np.int16)
    return tone


def play_audio(samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    """Play int16 numpy array through default output device."""
    try:
        sd.play(samples, samplerate=sample_rate, dtype=DTYPE)
        sd.wait()
    except Exception as e:
        logger.warning("Audio playback failed: %s", e)


def generate_beep_wav(freq: int = 880, duration_ms: int = 150, volume: float = 0.3) -> bytes:
    """Generate beep as WAV bytes (used as fallback)."""
    n_samples = int(SAMPLE_RATE * duration_ms / 1000)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        for i in range(n_samples):
            t = i / SAMPLE_RATE
            sample = int(volume * 32767 * np.sin(2 * np.pi * freq * t))
            wf.writeframes(struct.pack("<h", max(-32768, min(32767, sample))))
    return buf.getvalue()


BEEP = generate_beep(880, 150, 0.3)
BEEP_LOW = generate_beep(440, 200, 0.2)


# ---------------------------------------------------------------------------
# TTS via piper
# ---------------------------------------------------------------------------

def speak(text: str) -> None:
    """Speak text using piper TTS. Tries piper-tts Python package first, then binary."""
    if not text or not text.strip():
        return

    logger.info("Speaking: %s", text[:100])

    # Try 1: piper-tts Python module
    try:
        _speak_piper_python(text)
        return
    except Exception as e:
        logger.debug("piper Python module failed: %s", e)

    # Try 2: piper binary
    piper_bin = shutil.which("piper") or str(Path.home() / ".local" / "bin" / "piper")
    if Path(piper_bin).is_file():
        try:
            _speak_piper_binary(text, piper_bin)
            return
        except Exception as e:
            logger.debug("piper binary failed: %s", e)

    # Try 3: espeak-ng fallback
    espeak_bin = shutil.which("espeak-ng") or shutil.which("espeak")
    if espeak_bin:
        try:
            subprocess.run([espeak_bin, text], timeout=30, check=False)
            return
        except Exception as e:
            logger.debug("espeak failed: %s", e)

    logger.warning("No TTS backend available. Cannot speak: %s", text[:80])


def _speak_piper_python(text: str) -> None:
    """Use piper-tts Python package."""
    from piper import PiperVoice  # type: ignore[import-untyped]

    voice_path = Path(PIPER_VOICE)
    if not voice_path.exists():
        raise FileNotFoundError(f"Piper voice not found: {voice_path}")

    config_path = voice_path.with_suffix(".onnx.json")
    voice = PiperVoice.load(str(voice_path), config_path=str(config_path) if config_path.exists() else None)

    # Synthesize to WAV in memory
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        voice.synthesize(text, wf)

    buf.seek(0)
    with wave.open(buf, "rb") as wf:
        sr = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
        audio = np.frombuffer(frames, dtype=np.int16)

    sd.play(audio, samplerate=sr, dtype="int16")
    sd.wait()


def _speak_piper_binary(text: str, piper_bin: str) -> None:
    """Use piper CLI binary."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        proc = subprocess.run(
            [piper_bin, "--model", PIPER_VOICE, "--output_file", tmp_path],
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=60,
            check=True,
        )

        with wave.open(tmp_path, "rb") as wf:
            sr = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
            audio = np.frombuffer(frames, dtype=np.int16)

        sd.play(audio, samplerate=sr, dtype="int16")
        sd.wait()
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Wake word detection
# ---------------------------------------------------------------------------

def wait_for_wake_word() -> None:
    """Block until wake word is detected using openwakeword."""
    from openwakeword.model import Model  # type: ignore[import-untyped]

    logger.info("Loading wake word model: %s", WAKE_WORD_MODEL)
    oww_model = Model(wakeword_models=[WAKE_WORD_MODEL], inference_framework="onnx")

    # openwakeword expects 1280-sample chunks (80ms at 16kHz)
    OWW_CHUNK = 1280
    THRESHOLD = 0.5

    logger.info("Listening for wake word '%s'...", WAKE_WORD_MODEL)

    # Use a blocking stream for simplicity
    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype=DTYPE,
        blocksize=OWW_CHUNK,
    ) as stream:
        while True:
            audio_chunk, overflowed = stream.read(OWW_CHUNK)
            if overflowed:
                logger.debug("Audio buffer overflowed")

            # openwakeword expects int16 numpy array
            chunk_int16 = audio_chunk.flatten().astype(np.int16)
            prediction = oww_model.predict(chunk_int16)

            for model_name, score in prediction.items():
                if score > THRESHOLD:
                    logger.info("Wake word detected! model=%s score=%.3f", model_name, score)
                    oww_model.reset()
                    return


# ---------------------------------------------------------------------------
# Recording with VAD
# ---------------------------------------------------------------------------

def record_until_silence() -> np.ndarray:
    """Record audio until silence detected via webrtcvad. Returns int16 numpy array."""
    import webrtcvad  # type: ignore[import-untyped]

    vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
    frames_per_chunk = FRAME_SIZE  # 480 samples = 30ms at 16kHz

    recorded_frames: list[np.ndarray] = []
    silence_frames = 0
    max_silence_frames = int(SILENCE_TIMEOUT_S * 1000 / FRAME_DURATION_MS)
    max_total_frames = int(MAX_RECORD_S * 1000 / FRAME_DURATION_MS)
    total_frames = 0
    speech_detected = False

    logger.info("Recording... (silence timeout=%.1fs, max=%ds)", SILENCE_TIMEOUT_S, MAX_RECORD_S)

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype=DTYPE,
        blocksize=frames_per_chunk,
    ) as stream:
        while total_frames < max_total_frames:
            audio_chunk, overflowed = stream.read(frames_per_chunk)
            chunk_int16 = audio_chunk.flatten().astype(np.int16)
            recorded_frames.append(chunk_int16)
            total_frames += 1

            # webrtcvad needs raw bytes, 2 bytes per sample (int16)
            raw_bytes = chunk_int16.tobytes()
            is_speech = vad.is_speech(raw_bytes, SAMPLE_RATE)

            if is_speech:
                speech_detected = True
                silence_frames = 0
            else:
                silence_frames += 1

            # Only stop after we've heard some speech, then silence
            if speech_detected and silence_frames >= max_silence_frames:
                logger.info("Silence detected after speech. Stopping recording.")
                break

    duration_s = total_frames * FRAME_DURATION_MS / 1000
    logger.info("Recorded %.1fs of audio (%d frames)", duration_s, total_frames)

    if not recorded_frames:
        return np.array([], dtype=np.int16)

    return np.concatenate(recorded_frames)


# ---------------------------------------------------------------------------
# STT via faster-whisper
# ---------------------------------------------------------------------------

_whisper_model = None


def get_whisper_model():
    """Lazy-load the faster-whisper model."""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel  # type: ignore[import-untyped]

        logger.info("Loading faster-whisper model: %s", WHISPER_MODEL)
        _whisper_model = WhisperModel(
            WHISPER_MODEL,
            device="cpu",
            compute_type="int8",
        )
        logger.info("Whisper model loaded.")
    return _whisper_model


def transcribe(audio: np.ndarray) -> str:
    """Transcribe int16 audio to text using faster-whisper."""
    if len(audio) == 0:
        return ""

    model = get_whisper_model()

    # faster-whisper expects float32 normalized to [-1, 1]
    audio_f32 = audio.astype(np.float32) / 32768.0

    segments, info = model.transcribe(
        audio_f32,
        beam_size=5,
        language="en",
        vad_filter=True,
    )

    text_parts = []
    for segment in segments:
        text_parts.append(segment.text.strip())

    full_text = " ".join(text_parts).strip()
    logger.info("Transcription: %r (lang=%s prob=%.2f)", full_text[:100], info.language, info.language_probability)
    return full_text


# ---------------------------------------------------------------------------
# ASHI daemon interaction
# ---------------------------------------------------------------------------

def dispatch_to_ashi(text: str) -> str:
    """Send transcribed text to ASHI daemon, poll for result, return response text."""
    if not text:
        return "I didn't catch that."

    logger.info("Dispatching to ASHI: %r", text[:100])

    try:
        # POST the goal
        resp = httpx.post(
            f"{ASHI_DAEMON_URL}/agent/run",
            json={"goal": text, "max_steps": 10, "require_confirmation": False},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        tcu_id = data["tcu_id"]
        logger.info("Agent run started: tcu_id=%s", tcu_id)

    except httpx.ConnectError:
        logger.error("Cannot connect to ASHI daemon at %s", ASHI_DAEMON_URL)
        return "ASHI is offline."
    except Exception as e:
        logger.error("Failed to dispatch to ASHI: %s", e)
        return f"Error dispatching command: {e}"

    # Poll for completion
    start = time.monotonic()
    while time.monotonic() - start < POLL_TIMEOUT_S:
        try:
            status_resp = httpx.get(
                f"{ASHI_DAEMON_URL}/agent/status/{tcu_id}",
                timeout=5.0,
            )
            status_resp.raise_for_status()
            status_data = status_resp.json()

            status = status_data.get("status", "unknown")
            if status in ("completed", "done", "success"):
                final_output = status_data.get("final_output", "")
                if final_output:
                    return final_output
                # Fallback: join outputs
                outputs = status_data.get("outputs", [])
                if outputs:
                    return " ".join(str(o) for o in outputs[-3:])
                return "Done."

            if status in ("failed", "error", "denied"):
                error = status_data.get("error", "Unknown error")
                return f"Task failed: {error}"

            if status == "awaiting_confirmation":
                return "The task needs your confirmation in the ASHI dashboard."

        except Exception as e:
            logger.warning("Poll error: %s", e)

        time.sleep(POLL_INTERVAL_S)

    return "Task is still running. Check the ASHI dashboard for results."


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def check_daemon_online() -> bool:
    """Check if the ASHI daemon is reachable."""
    try:
        resp = httpx.get(f"{ASHI_DAEMON_URL}/health", timeout=3.0)
        return resp.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Main voice loop
# ---------------------------------------------------------------------------

_running = True


def _handle_signal(signum, frame):
    global _running
    logger.info("Received signal %d, shutting down...", signum)
    _running = False


def main() -> None:
    global _running

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("=== ASHI Voice Daemon starting ===")

    # Startup announcement
    if check_daemon_online():
        speak("ASHI online")
    else:
        speak("ASHI is offline")
        logger.warning("ASHI daemon not reachable at %s — will keep trying", ASHI_DAEMON_URL)

    # Pre-warm whisper model in background
    try:
        get_whisper_model()
    except Exception as e:
        logger.error("Failed to load whisper model: %s", e)
        speak("Warning: speech recognition model failed to load.")

    logger.info("Voice loop starting. Wake word: %s", WAKE_WORD_MODEL)

    while _running:
        try:
            # Step 1: Wait for wake word
            wait_for_wake_word()

            if not _running:
                break

            # Step 2: Play acknowledgement beep
            play_audio(BEEP)

            # Step 3: Record until silence
            audio = record_until_silence()

            if len(audio) < SAMPLE_RATE * 0.3:
                # Less than 300ms of audio — probably noise
                logger.info("Recording too short, ignoring.")
                play_audio(BEEP_LOW)
                continue

            # Step 4: Transcribe
            play_audio(BEEP_LOW)  # low beep = processing
            text = transcribe(audio)
            logger.info("User said: %r", text)

            if not text or len(text.strip()) < 2:
                speak("I didn't catch that. Try again.")
                continue

            # Step 5: Dispatch to ASHI daemon
            response = dispatch_to_ashi(text)

            # Step 6: Speak response
            speak(response)

        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error("Voice loop error: %s", e, exc_info=True)
            time.sleep(2)  # avoid tight error loops

    logger.info("=== ASHI Voice Daemon stopped ===")


if __name__ == "__main__":
    main()
