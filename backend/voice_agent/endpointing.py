"""
Endpointing: turning Silero's stream of probabilities (one every 32 ms) into the two events
a voice agent actually needs - "the caller started talking" and "the caller finished their
turn".

No model here. It's a small state machine driven by two thresholds and some counters:

             probability >= START_THRESHOLD for at least MIN_SPEECH_MS
   +---------+ ---------------------------------------------------------> +----------+
   | SILENT  |                                                            | SPEAKING |
   +---------+ <--------------------------------------------------------- +----------+
             probability < END_THRESHOLD for at least MIN_SILENCE_MS

Each setting fixes a specific failure seen in step 2's log:
  - START vs END threshold (hysteresis): a lower bar for "stopped" than for "started", so a
    probability hovering at 0.48 can't flip the state on and off.
  - MIN_SPEECH_MS: a burst shorter than this ("mm", a click - the single-window blip at
    24s in step 2) is ignored instead of starting a turn.
  - MIN_SILENCE_MS: a breath or a pause to think mid-sentence doesn't end the turn. This
    one is the latency trade-off: every turn ends at least this long after the caller
    actually stops.
  - PRE_ROLL_MS: we only confirm speech MIN_SPEECH_MS after it began, so recent audio is
    kept in a rolling buffer and prepended - otherwise STT would lose the first syllable.

All settings can be overridden with environment variables of the same name, so they can be
changed for an experiment without editing code, e.g.
    MIN_SILENCE_MS=300 uvicorn backend.voice_agent.server:app --port 8081
"""

import math
import os
from collections import deque
from dataclasses import dataclass

import numpy as np

WINDOW_MS = 32  # Silero's window: 512 samples at 16 kHz
TAIL_MS = 100  # quiet audio kept after the last speech, so soft word endings aren't clipped


def _setting(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


START_THRESHOLD = _setting("START_THRESHOLD", 0.50)
END_THRESHOLD = _setting("END_THRESHOLD", 0.35)
MIN_SPEECH_MS = _setting("MIN_SPEECH_MS", 250)
MIN_SILENCE_MS = _setting("MIN_SILENCE_MS", 700)
PRE_ROLL_MS = _setting("PRE_ROLL_MS", 300)


def _windows(ms: float) -> int:
    return math.ceil(ms / WINDOW_MS)


@dataclass
class SpeechStart:
    at: float  # seconds of audio since the track started, when speech actually began


@dataclass
class SpeechEnd:
    started_at: float
    ended_at: float  # when the silence that ended the turn began, not when it was detected
    silence_ms: int  # how long the silence had lasted when the turn was declared over
    audio: np.ndarray  # float32, 16 kHz mono: pre-roll + speech + a short tail


@dataclass
class Blip:
    at: float
    duration_ms: int


class Endpointer:
    """One per audio track - it holds the state of one conversation."""

    def __init__(self) -> None:
        self.min_speech_windows = max(1, _windows(MIN_SPEECH_MS))
        self.min_silence_windows = max(1, _windows(MIN_SILENCE_MS))
        self.tail_windows = _windows(TAIL_MS)

        self._index = 0  # windows seen so far; index * 32 ms = audio time
        self._speaking = False
        self._pre_roll: deque[np.ndarray] = deque(maxlen=_windows(PRE_ROLL_MS))
        self._candidate: list[np.ndarray] = []  # speech not yet long enough to count
        self._utterance: list[np.ndarray] = []
        self._started_at = 0.0
        self._silence_run = 0

    @staticmethod
    def describe_settings() -> str:
        return (
            f"start>={START_THRESHOLD:.2f}  end<{END_THRESHOLD:.2f}  "
            f"min_speech={MIN_SPEECH_MS:.0f}ms ({max(1, _windows(MIN_SPEECH_MS))} windows)  "
            f"min_silence={MIN_SILENCE_MS:.0f}ms ({max(1, _windows(MIN_SILENCE_MS))} windows)  "
            f"pre_roll={PRE_ROLL_MS:.0f}ms ({_windows(PRE_ROLL_MS)} windows)"
        )

    def process(self, probability: float, window: np.ndarray) -> list:
        """Feed one 32 ms window. Returns the events it caused (usually none)."""
        index = self._index
        self._index += 1
        if self._speaking:
            return self._while_speaking(probability, window)
        return self._while_silent(index, probability, window)

    def _while_silent(self, index: int, probability: float, window: np.ndarray) -> list:
        if probability >= START_THRESHOLD:
            self._candidate.append(window)
            if len(self._candidate) < self.min_speech_windows:
                return []
            # Long enough - it's real speech. It began when the candidate run began, and
            # the pre-roll adds the audio just before that.
            first = index - len(self._candidate) + 1
            self._started_at = first * WINDOW_MS / 1000
            self._utterance = list(self._pre_roll) + self._candidate
            self._candidate, self._silence_run, self._speaking = [], 0, True
            self._pre_roll.clear()
            return [SpeechStart(at=self._started_at)]

        events = []
        if self._candidate:
            # Speech started but stopped before MIN_SPEECH_MS - a blip, not a turn.
            first = index - len(self._candidate)
            events.append(Blip(at=first * WINDOW_MS / 1000, duration_ms=len(self._candidate) * WINDOW_MS))
            self._pre_roll.extend(self._candidate)
            self._candidate = []
        self._pre_roll.append(window)
        return events

    def _while_speaking(self, probability: float, window: np.ndarray) -> list:
        self._utterance.append(window)
        # Hysteresis: anything at or above END_THRESHOLD (not START_THRESHOLD) still counts
        # as speech here, so a 0.48 doesn't start the "turn over" countdown.
        if probability >= END_THRESHOLD:
            self._silence_run = 0
            return []

        self._silence_run += 1
        if self._silence_run < self.min_silence_windows:
            return []
        return [self._end_turn()]

    def _end_turn(self) -> SpeechEnd:
        # Drop the trailing silence that ended the turn, except a short tail.
        keep = len(self._utterance) - self._silence_run + self.tail_windows
        audio = np.concatenate(self._utterance[:keep])
        ended_at = (self._index - self._silence_run) * WINDOW_MS / 1000
        event = SpeechEnd(
            started_at=self._started_at,
            ended_at=ended_at,
            silence_ms=self._silence_run * WINDOW_MS,
            audio=audio,
        )
        self._speaking, self._utterance, self._silence_run = False, [], 0
        return event

    def flush(self) -> SpeechEnd | None:
        """The track ended (caller hung up / clicked Stop). If they were mid-sentence,
        close the turn now instead of losing it."""
        if not self._speaking:
            return None
        return self._end_turn()
