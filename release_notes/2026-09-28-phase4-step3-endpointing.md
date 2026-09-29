# Phase 4, step 3: endpointing

## What changed

Silero's stream of probabilities (one every 32 ms) now drives an **endpointer**. It turns
them into the two events a voice agent needs, "the caller started talking" and "the caller
finished their turn", ignores short blips, and saves each finished utterance as a `.wav`
file. That file is exactly the audio step 4 will send to speech-to-text. There's still no
STT, LLM or TTS.

- **`backend/voice_agent/endpointing.py`** (new): `Endpointer`, a two-state machine
  (`SILENT` / `SPEAKING`). Four settings, all overridable by environment variable.
- **`backend/voice_agent/vad.py`**: `process()` now returns each window's audio alongside its
  probability, so the endpointer can collect the exact audio the decision was made on.
- **`backend/voice_agent/server.py`**:
  - Feeds every VAD window to the endpointer and logs `SPEECH START`, `SPEECH END` and
    `ignored blip`.
  - Saves utterances to `backend/voice_agent/recordings/<call time>/utterance_NNNN.wav`,
    which is gitignored.
  - Closes a turn cut off by Stop or a hang-up instead of losing it.
  - Logs the active settings at startup.
  - Makes step 2's per-second line optional with `LOG_VAD_EVERY_SECOND=1`.
- **`tests/test_endpointing.py`** (new): 8 tests with made-up probabilities. They need no
  mic, server, model or network.

## The design

```
             probability >= 0.50 for at least 250 ms
   +---------+ ---------------------------------------> +----------+
   | SILENT  |                                          | SPEAKING |
   +---------+ <--------------------------------------- +----------+
             probability < 0.35 for at least 700 ms
```

No model here. It's two comparisons and two counters, which makes it plain code.

| Setting | Default | Fixes (from step 2's log) | Kind |
|---|---|---|---|
| `START_THRESHOLD` | 0.50 | when to start counting speech | equation (comparison) |
| `END_THRESHOLD` | 0.35 | **hysteresis**: a lower bar for "stopped" than "started", so 0.48 (33s) can't flip the state | equation |
| `MIN_SPEECH_MS` | 250 (8 windows) | a blip shorter than this is ignored (24s) | code (counter) |
| `MIN_SILENCE_MS` | 700 (22 windows) | a breath or pause doesn't end the turn (21s) | code (counter) |
| `PRE_ROLL_MS` | 300 (10 windows) | speech is only confirmed 250 ms after it began, so recent audio is kept and prepended, or STT would lose the first syllable | code (ring buffer) |

Two details:

- **Times are audio time**, in seconds since the call started. `SPEECH START` is when speech
  actually began, not the moment it was confirmed. `SPEECH END` is when the silence began,
  not when it was detected `MIN_SILENCE_MS` later.
- **The saved audio** is pre-roll + speech + a 100 ms tail. The rest of the ending silence
  is dropped, and the tail keeps soft word endings like "s" from being clipped.

## Test cases to run

### Automated (no mic)

```bash
pytest tests/test_endpointing.py -v
```

### Live

Start the server:

```bash
uvicorn backend.voice_agent.server:app --host 0.0.0.0 --port 8081
```

Open http://localhost:8081, then run these one at a time:

| # | Do this | Expect |
|---|---|---|
| 1 | Say one sentence, then stop | `SPEECH START`, then `SPEECH END` ~0.7 s after you stop, and a saved `.wav` |
| 2 | Say "mm", cough, or tap the desk | `ignored blip: … ms`, no `SPEECH START` |
| 3 | "I'd like… (short pause) …a table for two" | one START and one END: the pause stays inside the turn |
| 4 | Same sentence, but a long pause (2 s) in the middle | two separate utterances |
| 5 | Talk, then click Stop mid-sentence | a final `SPEECH END` anyway, and the saved `.wav` isn't lost |
| 6 | Restart with `MIN_SILENCE_MS=300` and repeat #3 | the short pause now splits the turn: the agent would cut you off |
| 7 | Restart with `MIN_SILENCE_MS=1500` and repeat #1 | END comes ~1.5 s after you stop: never cuts you off, but slow |
| 8 | Play the saved `.wav` files | the first syllable is present |
| 9 | Restart with `PRE_ROLL_MS=0` and repeat #1, then play it | the first syllable is clipped |
| 10 | Say just "yes", pause, then just "no" (added after run 1) | each is a full turn (START + END), **not** an `ignored blip`. If they're dropped, `MIN_SPEECH_MS` is too high for one-word confirmations |

The startup line `Endpointing settings: …` confirms which values each run used.

Tests 6 and 7 are the trade-off from the plan's latency table (endpointing target 200–500
ms): shorter cuts people off, longer adds delay to every turn. The semantic turn detection
in a later step exists to get out of this trade-off.

## Fix: pure tests no longer need Postgres

The first run of `pytest tests/test_endpointing.py` showed all 8 tests as **ERROR** (not
FAILED), because Postgres was stopped. `tests/conftest.py` had two `autouse` fixtures that
connected to the database before and after **every** test in `tests/`, even tests that
never use it. The earlier pure tests (formatting, LLM config) only passed because Postgres
happened to be running whenever they ran.

- **`tests/conftest.py`:** the two fixtures are now one `_database` fixture. It loads the
  menu once and cleans up test rows as before, but skips entirely for tests marked `no_db`.
- **`pytest.ini`:** registers the `no_db` marker.
- **`tests/test_endpointing.py`, `tests/test_formatting.py`, `tests/test_llm_config.py`:**
  marked `no_db`, so they run without Docker.

Result after the fix, with Postgres still stopped:

```
tests/test_endpointing.py::test_default_settings_convert_to_the_expected_window_counts PASSED
tests/test_endpointing.py::test_a_short_blip_is_ignored_not_treated_as_speech PASSED
tests/test_endpointing.py::test_sustained_speech_starts_and_ends_a_turn_with_the_right_times PASSED
tests/test_endpointing.py::test_utterance_audio_has_the_pre_roll_and_a_short_tail_but_not_the_whole_silence PASSED
tests/test_endpointing.py::test_hysteresis_a_value_between_the_two_thresholds_does_not_end_the_turn PASSED
tests/test_endpointing.py::test_a_pause_shorter_than_min_silence_does_not_end_the_turn PASSED
tests/test_endpointing.py::test_flush_closes_a_turn_that_was_cut_off_by_hanging_up PASSED
tests/test_endpointing.py::test_flush_does_nothing_when_nobody_is_speaking PASSED
```

What each one proves:

| Test | Proves |
|---|---|
| default settings → window counts | 250 ms → 8 windows, 700 ms → 22 windows (the rounding seen as "704 ms" in run 1) |
| short blip ignored | 3 windows (96 ms) of speech gives a `Blip`, never a `SpeechStart` |
| start/end times | START is back-dated to when speech began; END to when silence began, not when it was detected |
| pre-roll and tail | the saved audio is 10 pre-roll + all speech + 4 tail windows, not the full 22 of silence |
| hysteresis | once speaking, 0.45 still counts as speech, so hovering near 0.5 doesn't end the turn |
| short pause | 320 ms of quiet mid-sentence stays one turn |
| flush while speaking | hanging up mid-sentence still produces a `SpeechEnd` |
| flush while silent | nothing to save, nothing returned |

## What we observed

### Run 1: default settings (2026-09-28)

Settings: start ≥ 0.50, end < 0.35, min speech 250 ms, min silence 700 ms, pre-roll 300 ms.
The call was ended with Ctrl+C on the server (not the page's Stop button), while nobody was
speaking.

#### The full log

```
[ 2026-09-28 16:37:08,312 ] aioice.ice - INFO - Connection(0) Check CandidatePair(('172.21.0.1', 54412) -> ('192.168.1.39', 52526)) State.FROZEN -> State.IN_PROGRESS
[ 2026-09-28 16:37:08,529 ] aioice.ice - INFO - Connection(0) Check CandidatePair(('172.17.211.55', 55646) -> ('172.17.208.1', 52525)) State.IN_PROGRESS -> State.SUCCEEDED
[ 2026-09-28 16:37:08,531 ] aioice.ice - INFO - Connection(0) ICE completed
[ 2026-09-28 16:37:08,555 ] root - INFO - Connection state: connected
[ 2026-09-28 16:37:08,657 ] root - INFO - Resampled: 48000 Hz stereo, 960 samples/frame  ->  16000 Hz mono, 304 samples/frame
[ 2026-09-28 16:37:09,694 ] root - INFO -    0.80s  SPEECH START
[ 2026-09-28 16:37:13,670 ] root - INFO -    4.26s  SPEECH END    3.46s of speech (turn ended after 704 ms of silence) -> recordings/20260928_163702/utterance_0001.wav
[ 2026-09-28 16:37:13,771 ] root - INFO -    5.06s  ignored blip: 32 ms (below the 250 ms minimum)
[ 2026-09-28 16:37:13,852 ] root - INFO -    5.12s  ignored blip: 64 ms (below the 250 ms minimum)
[ 2026-09-28 16:37:14,333 ] root - INFO -    5.63s  ignored blip: 32 ms (below the 250 ms minimum)
[ 2026-09-28 16:37:15,270 ] root - INFO -    6.37s  SPEECH START
[ 2026-09-28 16:37:21,965 ] root - INFO -   12.54s  SPEECH END    6.18s of speech (turn ended after 704 ms of silence) -> recordings/20260928_163702/utterance_0002.wav
[ 2026-09-28 16:37:23,612 ] root - INFO -   14.72s  SPEECH START
[ 2026-09-28 16:37:29,859 ] root - INFO -   20.42s  SPEECH END    5.70s of speech (turn ended after 704 ms of silence) -> recordings/20260928_163702/utterance_0003.wav
[ 2026-09-28 16:37:30,912 ] root - INFO -   22.02s  SPEECH START
[ 2026-09-28 16:37:33,763 ] root - INFO -   24.35s  SPEECH END    2.34s of speech (turn ended after 704 ms of silence) -> recordings/20260928_163702/utterance_0004.wav
[ 2026-09-28 16:37:34,593 ] root - INFO -   25.89s  ignored blip: 32 ms (below the 250 ms minimum)
[ 2026-09-28 16:37:40,935 ] root - INFO -   32.03s  SPEECH START
[ 2026-09-28 16:37:58,108 ] root - INFO -   48.64s  SPEECH END    16.61s of speech (turn ended after 704 ms of silence) -> recordings/20260928_163702/utterance_0005.wav
[ 2026-09-28 16:37:58,652 ] root - INFO -   49.95s  ignored blip: 32 ms (below the 250 ms minimum)
[ 2026-09-28 16:38:00,031 ] root - INFO -   51.20s  ignored blip: 160 ms (below the 250 ms minimum)
[ 2026-09-28 16:38:00,134 ] root - INFO -   51.39s  ignored blip: 64 ms (below the 250 ms minimum)
^CINFO:     Shutting down
INFO:     Waiting for application shutdown.
[ 2026-09-28 16:38:00,860 ] root - INFO - Audio track ended after 2611 frames, 5 utterance(s)
[ 2026-09-28 16:38:00,865 ] root - INFO - Connection state: closed
INFO:     Application shutdown complete.
INFO:     Finished server process [29169]
```

The explanation below works through this log section by section.

#### What happened, turn by turn

| Turn | Started | Ended | Speech | Then |
|---|---|---|---|---|
| 1 | 0.80s | 4.26s | 3.46s | 3 blips at 5.06, 5.12, 5.63s, all ignored |
| 2 | 6.37s | 12.54s | 6.18s | |
| 3 | 14.72s | 20.42s | 5.70s | |
| 4 | 22.02s | 24.35s | 2.34s | 1 blip at 25.89s, ignored |
| 5 | 32.03s | 48.64s | **16.61s** | 3 blips at 49.95, 51.20, 51.39s, ignored |

That's 5 turns and 34.3 s of speech in a 52 s call (2611 frames × 20 ms). Each turn was
saved as its own `.wav`.

#### 1. The 700 ms setting shows up as 704 ms

Every END says `turn ended after 704 ms of silence`, not 700. The endpointer counts in whole
32 ms windows: 700 ÷ 32 = 21.9, which rounds up to 22 windows, and 22 × 32 = 704 ms. Time
here only moves in 32 ms steps, so no setting can be more precise than that.

#### 2. The logged times are back-dated

The log line and the time it reports are two different moments:

- **START:** the event for turn 1 says `0.80s`, meaning the moment speech began. It could
  only be *confirmed* 8 windows (256 ms) later, once it was clearly speech and not a blip. So
  it's logged late but stamped with the real start time.
- **END:** the event says `4.26s`, meaning the moment the speaker went quiet. It was only
  *detected* 704 ms after that.

The wall-clock timestamps on the left confirm this:

- **Audio time** from START (0.80s) to END (4.26s) is **3.46 s**.
- **Wall time** from the START log line (16:37:09.694) to the END log line (16:37:13.670) is
  **3.98 s**.
- **The 0.52 s gap** between them is roughly 704 ms (END detection) − 256 ms (START
  detection) = 448 ms, plus a few tens of milliseconds of processing and network jitter.

The design is behaving exactly as written, and you can prove it from the log alone.

**The 704 ms is what the caller would feel.** It's the time between the caller going quiet
and the agent even knowing it's allowed to reply. STT, the LLM and TTS all come after that.
The plan's target for this piece alone is 200–500 ms, so the default is on the slow side on
purpose. Test 6 is where you can see what happens when it's shorter.

#### 3. The blips show the filter working, and its limits

Seven sounds were ignored: 32, 64, 32, 32, 32, **160**, 64 ms. Most came right after a
sentence finished. Lip smacks, breaths and the start of an "um" often happen just after a
sentence ends.

The **160 ms** one at 51.20s is the one to think about. It's more than half of the 250 ms
minimum, and a short one-word answer like "yes" or "no" can take about 200–300 ms. **So a
caller answering "yes" to "shall I confirm your order?" could be thrown away as a blip.**
That's the other side of `MIN_SPEECH_MS`:

- **Raise it:** fewer false starts, but short answers get lost.
- **Lower it:** short answers are kept, but more noise starts turns.

This matters a lot for this project, because confirming orders and reservations depends on
exactly that one-word "yes".

#### 4. Turn 5 was 16.6 seconds with no break

In 16.6 s there was never a 704 ms pause. As a transcript that's fine. For a voice agent,
it's a caller talking for a long time with the agent unable to respond, which is where
barge-in and back-channel ("mm-hm") design will matter later.

#### 5. What this run didn't test

- **The Stop-mid-sentence flush (test 5):** the call ended with Ctrl+C on the server while
  nobody was speaking, so there was no open turn to save. `5 utterance(s)` came only from
  normal endings.
- **Short vs long pauses and the settings experiments (tests 3, 4, 6, 7, 9):** they aren't
  clearly visible in this log. Every gap between turns was 1.6 s or more, well above 704 ms.
- **New test added: a one-word "yes" and "no",** said on their own, to see whether they pass
  the 250 ms minimum or get dropped as blips.
