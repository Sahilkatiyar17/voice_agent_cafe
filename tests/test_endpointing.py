"""
Tests backend/voice_agent/endpointing.py with made-up probabilities - no microphone, no
server, no Silero model. Each window's audio is filled with its own index number, so a
test can check exactly which windows ended up in a saved utterance.

These assume the default settings (no START_THRESHOLD / MIN_SILENCE_MS / ... environment
variables set):
  min speech  250 ms -> 8 windows
  min silence 700 ms -> 22 windows
  pre-roll    300 ms -> 10 windows
  tail        100 ms -> 4 windows
"""

import pytest

from backend.voice_agent.endpointing import Blip, Endpointer, SpeechEnd, SpeechStart

pytestmark = pytest.mark.no_db  # pure logic - runs without Postgres

SILENCE, SPEECH = 0.02, 0.95


def _feed(endpointer: Endpointer, probabilities: list[float], start_index: int = 0) -> list:
    """Feeds one window per probability. Window i's audio is 512 copies of i."""
    import numpy as np

    events = []
    for offset, p in enumerate(probabilities):
        events.extend(endpointer.process(p, np.full(512, start_index + offset, dtype=np.float32)))
    return events


def test_default_settings_convert_to_the_expected_window_counts():
    e = Endpointer()
    assert e.min_speech_windows == 8
    assert e.min_silence_windows == 22


def test_a_short_blip_is_ignored_not_treated_as_speech():
    """Step 2's log, 24s: one window crossed 0.5. Three windows (96 ms) is still below the
    250 ms minimum."""
    events = _feed(Endpointer(), [SILENCE] * 20 + [SPEECH] * 3 + [SILENCE] * 10)

    assert not any(isinstance(ev, SpeechStart) for ev in events)
    blips = [ev for ev in events if isinstance(ev, Blip)]
    assert len(blips) == 1
    assert blips[0].duration_ms == 96
    assert abs(blips[0].at - 20 * 0.032) < 1e-9


def test_sustained_speech_starts_and_ends_a_turn_with_the_right_times():
    events = _feed(Endpointer(), [SILENCE] * 20 + [SPEECH] * 30 + [SILENCE] * 30)

    starts = [ev for ev in events if isinstance(ev, SpeechStart)]
    ends = [ev for ev in events if isinstance(ev, SpeechEnd)]
    assert len(starts) == 1 and len(ends) == 1

    # Speech began at window 20, even though it was only confirmed 8 windows later.
    assert abs(starts[0].at - 20 * 0.032) < 1e-9
    # The turn ended where the silence began (window 50), not where it was detected (71).
    assert abs(ends[0].ended_at - 50 * 0.032) < 1e-9
    assert ends[0].silence_ms == 22 * 32


def test_utterance_audio_has_the_pre_roll_and_a_short_tail_but_not_the_whole_silence():
    events = _feed(Endpointer(), [SILENCE] * 20 + [SPEECH] * 30 + [SILENCE] * 30)
    end = next(ev for ev in events if isinstance(ev, SpeechEnd))

    windows = end.audio.reshape(-1, 512)[:, 0]  # the index number stamped on each window
    assert windows[0] == 10  # pre-roll: the 10 windows before speech began (10..19)
    assert list(windows[10:40]) == list(range(20, 50))  # all 30 speech windows
    assert len(windows) == 10 + 30 + 4  # plus a 4-window (~100 ms) tail, not all 22


def test_hysteresis_a_value_between_the_two_thresholds_does_not_end_the_turn():
    """Step 2's log, 33s: 0.48 sat just under 0.5. Once speaking, anything >= 0.35 still
    counts as speech, so hovering there doesn't start the end-of-turn countdown."""
    events = _feed(Endpointer(), [SPEECH] * 10 + [0.45] * 40)
    assert not any(isinstance(ev, SpeechEnd) for ev in events)


def test_a_pause_shorter_than_min_silence_does_not_end_the_turn():
    """A breath mid-sentence: 10 quiet windows (320 ms) is under the 700 ms minimum."""
    events = _feed(Endpointer(), [SPEECH] * 10 + [SILENCE] * 10 + [SPEECH] * 10)
    assert not any(isinstance(ev, SpeechEnd) for ev in events)
    assert sum(isinstance(ev, SpeechStart) for ev in events) == 1  # still one turn


def test_flush_closes_a_turn_that_was_cut_off_by_hanging_up():
    e = Endpointer()
    _feed(e, [SPEECH] * 20)
    assert isinstance(e.flush(), SpeechEnd)


def test_flush_does_nothing_when_nobody_is_speaking():
    e = Endpointer()
    _feed(e, [SILENCE] * 20)
    assert e.flush() is None
