# Phase 4, step 2: resample to 16 kHz mono, and Silero VAD

## What changed

Each incoming frame is now converted to the format speech models expect, then scored by
Silero VAD. Once a second, the server logs RMS loudness and the VAD speech probability side
by side, so the difference between them shows up in the numbers. There's still no STT, LLM
or TTS.

- **`backend/voice_agent/audio.py`** (new): `MonoResampler` converts 48 kHz stereo to 16 kHz
  mono using PyAV's `AudioResampler`.
- **`backend/voice_agent/vad.py`** (new): `SileroVAD` does four things:
  - Loads the same Silero model Phase 1's audio lab used (already cached, no download).
  - Buffers the incoming samples.
  - Scores every 512-sample window.
  - Resets between calls.
- **`backend/voice_agent/server.py`**:
  - Loads the VAD once at startup.
  - Resamples and scores every frame.
  - Logs a per-second summary line.
- **`backend/voice_agent/static/index.html`**: heading only.

## Concepts in this step

| Piece | Kind | What it actually does |
|---|---|---|
| Stereo → mono | **Equation** | Averages the left and right sample of each pair |
| 48 kHz → 16 kHz | **Equation** | A low-pass filter removes everything above 8 kHz, then 2 of every 3 samples are dropped |
| Silero VAD | **Model** | A small recurrent neural net. Each 32 ms window in, one speech probability (0–1) out |
| RMS, now per second | **Equation** | `sqrt(mean(x²))` over the whole second, not one 20 ms frame |

- **Why the low-pass filter comes first (Nyquist):**
  - A 16 kHz signal can only represent frequencies up to 8 kHz.
  - Anything higher left in would "fold back" as false low-frequency sound, called aliasing.
  - Losing everything above 8 kHz is fine for speech. It's the same trade-off as phone audio,
    which Phase 1's audio lab compared at 8 kHz.
- **Why 512 samples:**
  - Silero only accepts 512-sample windows at 16 kHz, which is 32 ms.
  - Frames arrive as about 320 samples (20 ms), which doesn't divide evenly into 512.
  - So `SileroVAD` buffers samples and carries the leftovers over to the next frame.
- **Why the model is reset per call:** Silero is a recurrent network, so it remembers the
  windows it has already seen. That's also why one instance can't serve two calls at once.
- **Fix to step 1's RMS:** it's now averaged over the whole second instead of taken from one
  20 ms frame, so a gap between words no longer reads as a silent second.

## What the log line means

```
  4.0s  rms=  612  vad_max=0.97 |##########|  speech windows 22/31
```

- **`vad_max`:** the highest speech probability in that second. The bar is the same number
  drawn out of 10.
- **`speech windows 22/31`:** how many of that second's 32 ms windows scored at or above 0.5,
  Silero's default cut-off.
- **`<- loud, but NOT speech` / `<- quiet, but IS speech`:** printed where RMS and VAD disagree.
  The RMS thresholds (500 / 200) are illustrative only. Nothing acts on them yet.

## Known limitations

- **One call at a time:** there's a single stateful Silero instance. That's fine for testing
  and will need fixing before real concurrent calls.

## How to run

```bash
uvicorn backend.voice_agent.server:app --host 0.0.0.0 --port 8081
```

Open http://localhost:8081, click Start, and try:

1. Normal speech.
2. A cough, a clap or a tap on the desk: this should come out loud but not speech.
3. Whispering: this should come out quiet but speech.
4. Silence.

## What we observed on the first run (2026-09-28)

During this run the speaker talked normally, went silent, and then **moved further away
from the laptop** while still talking, to test whether VAD still caught them. It did.

### The full log

```
[ 2026-09-28 15:47:15,619 ] aioice.ice - INFO - Connection(0) Check CandidatePair(('172.17.211.55', 45493) -> ('172.17.208.1', 55449)) State.IN_PROGRESS -> State.SUCCEEDED
[ 2026-09-28 15:47:15,622 ] aioice.ice - INFO - Connection(0) ICE completed
[ 2026-09-28 15:47:15,656 ] root - INFO - Connection state: connected
[ 2026-09-28 15:47:15,798 ] root - INFO - Resampled: 48000 Hz stereo, 960 samples/frame  ->  16000 Hz mono, 304 samples/frame
[ 2026-09-28 15:47:16,740 ] root - INFO -   1.0s  rms=  821  vad_max=0.59 |######    |  speech windows  2/31
[ 2026-09-28 15:47:17,740 ] root - INFO -   2.0s  rms= 1568  vad_max=0.99 |##########|  speech windows 12/31
[ 2026-09-28 15:47:18,739 ] root - INFO -   3.0s  rms= 1541  vad_max=1.00 |##########|  speech windows 30/31
[ 2026-09-28 15:47:19,739 ] root - INFO -   4.0s  rms= 2103  vad_max=1.00 |##########|  speech windows 31/31
[ 2026-09-28 15:47:20,741 ] root - INFO -   5.0s  rms= 1782  vad_max=1.00 |##########|  speech windows 32/32
[ 2026-09-28 15:47:21,738 ] root - INFO -   6.0s  rms=  693  vad_max=1.00 |##########|  speech windows 23/31
[ 2026-09-28 15:47:22,737 ] root - INFO -   7.0s  rms= 1027  vad_max=1.00 |##########|  speech windows 23/31
[ 2026-09-28 15:47:23,738 ] root - INFO -   8.0s  rms=   84  vad_max=0.13 |#         |  speech windows  0/31
[ 2026-09-28 15:47:24,740 ] root - INFO -   9.0s  rms=  171  vad_max=0.10 |#         |  speech windows  0/32
[ 2026-09-28 15:47:25,739 ] root - INFO -  10.0s  rms=   78  vad_max=0.01 |          |  speech windows  0/31
[ 2026-09-28 15:47:26,738 ] root - INFO -  11.0s  rms=  405  vad_max=0.17 |##        |  speech windows  0/31
[ 2026-09-28 15:47:27,739 ] root - INFO -  12.0s  rms= 2330  vad_max=1.00 |##########|  speech windows 20/31
[ 2026-09-28 15:47:28,737 ] root - INFO -  13.0s  rms= 2447  vad_max=1.00 |##########|  speech windows 32/32
[ 2026-09-28 15:47:29,739 ] root - INFO -  14.0s  rms= 1581  vad_max=1.00 |##########|  speech windows 26/31
[ 2026-09-28 15:47:30,737 ] root - INFO -  15.0s  rms= 1996  vad_max=1.00 |##########|  speech windows 25/31
[ 2026-09-28 15:47:31,740 ] root - INFO -  16.0s  rms= 1667  vad_max=1.00 |##########|  speech windows 31/31
[ 2026-09-28 15:47:32,740 ] root - INFO -  17.0s  rms= 1536  vad_max=1.00 |##########|  speech windows 32/32
[ 2026-09-28 15:47:33,738 ] root - INFO -  18.0s  rms= 1711  vad_max=1.00 |##########|  speech windows 31/31
[ 2026-09-28 15:47:34,738 ] root - INFO -  19.0s  rms= 1693  vad_max=1.00 |##########|  speech windows 22/31
[ 2026-09-28 15:47:35,738 ] root - INFO -  20.0s  rms= 1600  vad_max=1.00 |##########|  speech windows 31/31
[ 2026-09-28 15:47:36,741 ] root - INFO -  21.0s  rms=  327  vad_max=0.98 |##########|  speech windows  5/32
[ 2026-09-28 15:47:37,740 ] root - INFO -  22.0s  rms=  163  vad_max=0.03 |          |  speech windows  0/31
[ 2026-09-28 15:47:38,735 ] root - INFO -  23.0s  rms=  123  vad_max=0.02 |          |  speech windows  0/31
[ 2026-09-28 15:47:39,738 ] root - INFO -  24.0s  rms=  417  vad_max=0.59 |######    |  speech windows  1/31
[ 2026-09-28 15:47:40,738 ] root - INFO -  25.0s  rms=  209  vad_max=0.01 |          |  speech windows  0/32
[ 2026-09-28 15:47:41,739 ] root - INFO -  26.0s  rms=  943  vad_max=1.00 |##########|  speech windows 12/31
[ 2026-09-28 15:47:42,736 ] root - INFO -  27.0s  rms=  787  vad_max=1.00 |##########|  speech windows 31/31
[ 2026-09-28 15:47:43,737 ] root - INFO -  28.0s  rms= 1112  vad_max=1.00 |##########|  speech windows 31/31
[ 2026-09-28 15:47:44,740 ] root - INFO -  29.0s  rms=  745  vad_max=1.00 |##########|  speech windows 30/32
[ 2026-09-28 15:47:45,738 ] root - INFO -  30.0s  rms=  326  vad_max=0.99 |##########|  speech windows  8/31
[ 2026-09-28 15:47:46,739 ] root - INFO -  31.0s  rms=  441  vad_max=0.78 |########  |  speech windows  5/31
[ 2026-09-28 15:47:47,735 ] root - INFO -  32.0s  rms=  325  vad_max=0.11 |#         |  speech windows  0/31
[ 2026-09-28 15:47:48,740 ] root - INFO -  33.0s  rms=  366  vad_max=0.48 |#####     |  speech windows  0/32
[ 2026-09-28 15:47:49,737 ] root - INFO -  34.0s  rms=  961  vad_max=0.99 |##########|  speech windows 31/31
[ 2026-09-28 15:47:50,737 ] root - INFO -  35.0s  rms=  850  vad_max=1.00 |##########|  speech windows 31/31
[ 2026-09-28 15:47:51,736 ] root - INFO -  36.0s  rms=  794  vad_max=1.00 |##########|  speech windows 31/31
[ 2026-09-28 15:47:52,740 ] root - INFO -  37.0s  rms=  730  vad_max=1.00 |##########|  speech windows 29/32
[ 2026-09-28 15:47:53,739 ] root - INFO -  38.0s  rms=  386  vad_max=1.00 |##########|  speech windows 15/31
[ 2026-09-28 15:47:54,738 ] root - INFO -  39.0s  rms=  577  vad_max=0.91 |######### |  speech windows 13/31
[ 2026-09-28 15:47:55,736 ] root - INFO -  40.0s  rms=  189  vad_max=0.17 |##        |  speech windows  0/31
[ 2026-09-28 15:47:55,947 ] root - INFO - Audio track ended after 2010 frames
[ 2026-09-28 15:47:55,952 ] root - INFO - Connection state: closed
```

The explanation below works through this log section by section.

### 1. The path one 20 ms frame takes

```
browser mic
   │  Opus-encoded packets over WebRTC
   ▼
aiortc decodes ──▶ av.AudioFrame: 960 samples × 2 channels, int16, 48 kHz
   │
   ▼  MonoResampler (audio.py)
   │    1. average left+right            ──▶ 960 samples, mono
   │    2. low-pass filter at 8 kHz      ──▶ removes what 16 kHz can't represent
   │    3. keep 1 sample in 3            ──▶ ~320 samples, 16 kHz
   ▼
int16 ÷ 32768 ──▶ float32 in -1.0 … 1.0   (the scale Silero was trained on)
   │
   ▼  SileroVAD buffer (vad.py)
   │    frames add ~320 samples each; every time 512 are waiting, cut one window
   ▼
Silero model ──▶ one number, 0.0 … 1.0, per 32 ms window
```

Frames arrive every 20 ms but windows are 32 ms long. Five frames make 1,600 samples, which
is 3.125 windows. So the buffer always carries a few leftover samples into the next frame.
The log shows this directly:

- **Why the counts differ:** one second is 16,000 samples. 16,000 ÷ 512 = 31.25 windows. Most
  seconds get 31 windows. The 0.25 leftovers add up, so every fourth second gets 32.
- **Where to see it:** the log has `/32` at exactly 5s, 9s, 13s, 17s, 21s, 25s, 29s, 33s and
  37s. That's one every 4 seconds, which is the leftover buffer at work.

### 2. Why resampling has to come before the VAD

Silero was trained only on 16 kHz (and 8 kHz) audio. To the model, "512 samples" means 32 ms.

If you fed it the raw 48 kHz audio instead:

- **The window gets shorter:** 512 samples would cover only 10.7 ms.
- **Every frequency looks three times lower:** a voice at 200 Hz would look like 67 Hz to the
  model.

It's like playing a recording at one-third speed and asking someone whether it's speech. The
model's learned patterns wouldn't match, and the probabilities would be meaningless.
Resampling means the model sees audio at the same "speed" it was trained on.

**Why the log shows `304 samples/frame` instead of 320.** That was the first frame only. The
low-pass filter needs a few samples of look-ahead before it can produce output, so it held
back 16 samples at the start. Later frames catch up. This is why `audio.py` says to buffer
rather than assume a fixed size, and the log proved the point on the first frame.

### 3. What Silero is actually looking at

Roughly, the model works in three stages:

1. **Split the sound into frequency bands.** It does something like a Fourier transform on
   the window.
2. **Look for speech patterns in those bands.** It uses convolution layers.
3. **Remember what came before.** It passes the result through a recurrent layer (an LSTM).
   The LSTM keeps memory across windows, which is why `reset()` is needed per call.

The output goes through a sigmoid to give the 0-to-1 probability.

Speech has a shape that other sounds don't:

- **Harmonics.** A voiced sound has a pitch (roughly 85–255 Hz for adult voices) plus evenly
  spaced copies above it, like a comb.
- **Formants.** These are resonant peaks from the mouth and throat, roughly 300–3,000 Hz.
  Their positions change with each vowel.
- **Rhythm.** Speech rises and falls about 4–5 times a second, once per syllable.

Other sounds look different:

- **A fan:** a flat, steady hiss.
- **A clap or a tap:** a short burst across all frequencies with no harmonics.
- **A mouse click:** a spike.

Silero learned what speech looks like from a large amount of labelled audio.

### 4. The distance test is the whole point of this step

| Time | Where the speaker was (inferred) | RMS | VAD | Windows |
|---|---|---|---|---|
| 12–20s | close | **1,536 – 2,447** | 1.00 | 20–32 / 31 |
| 27–29s | further away | **745 – 1,112** | 1.00 | 30–31 / 31 |
| 35–37s | further away | **730 – 850** | 1.00 | 29–31 / 31 |

- **Loudness:** RMS roughly **halved or worse** when the speaker moved away. That's physics:
  sound amplitude falls off roughly with 1/distance, so doubling the distance halves the
  amplitude.
- **Speech detection:** VAD didn't move at all, **1.00** with almost every window counted as
  speech.

Moving away makes a voice quieter, but the harmonics, formants and rhythm are all still
there. RMS only measures size. Silero measures shape.

If this system used a loudness threshold, you'd have to choose between two bad options:

- **A low threshold** hears you from across the room but also triggers on noise.
- **A high threshold** ignores noise but misses you when you step back.

The model avoids that choice.

**Two things in the browser helped a little:**

- **`autoGainControl: true`** made the browser boost the quiet signal before we got it. So
  the RMS drop seen here is smaller than physics alone would give.
- **`noiseSuppression: true`** removed steady background noise first.

Both are still simple signal processing, not speech understanding. The model is what kept the
distant voice at 1.00.

### 5. The interesting rows

- **1.0s, `vad 0.59`, 2/31:** speech only started at the very end of that second.
- **8–10s, `rms 78–171`, `vad ≤ 0.13`:** real silence. Both measures agree.
- **11.0s, `rms 405`, `vad 0.17`:** something fairly loud that isn't speech, maybe a breath, a
  chair or a keyboard. It didn't get the `loud, but NOT speech` tag only because the
  illustrative threshold was 500.
- **21.0s, `vad 0.98` but only 5/32:** the tail of a sentence. About the first 160 ms of that
  second was speech, then it stopped.
- **24.0s, `vad 0.59`, 1/31:** a single 32 ms window crossed 0.5, maybe an "mm" or a click.
  **This is the case step 3 has to handle.** One window isn't someone starting to talk.
- **33.0s, `vad 0.48`:** just under 0.5. A single threshold gives a jumpy yes/no for sounds
  right on the line.

### 6. What this sets up for step 3 (endpointing)

The model gives a number every 32 ms. The voice agent needs just two events: "caller started
talking" and "caller finished their turn." Rows 21s, 24s and 33s show why a plain
`probability > 0.5` check isn't enough. Step 3 adds three rules, all plain code:

- **Two thresholds (hysteresis).** Speech starts above 0.5 but only ends below about 0.35.
  Values bouncing around 0.48 then don't flip the state on and off.
- **Minimum speech length.** Around 250 ms, so a single-window blip like 24s is ignored.
- **Minimum silence before "turn over".** Around 600–800 ms, so a pause to breathe
  mid-sentence doesn't end the turn.

That last number is the latency-versus-cutting-off trade-off the plan talks about. Changing it
shows the trade-off directly.

## Next (step 3)

The raw probabilities become events: speech started and speech ended. That's endpointing,
written by hand from the probabilities. It's the input step 4 needs to know when to send a
buffered utterance to STT.
