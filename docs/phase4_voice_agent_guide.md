# Phase 4 study guide: how the hand-built voice agent works

A reference for the maths and model structure behind each piece of the voice agent. The
release notes (`release_notes/`) record *what changed and what the runs showed*; this file
explains *why it works*. Read the two together: each section below points to the release
note with the real logs.

Every piece is tagged by what kind of thing it is:

- **Equation:** a fixed formula. Same input, same output, nothing learned.
- **Model:** a trained neural network. Learned weights, not written rules.
- **Code:** plain program logic (state, counters, buffers, networking).

Where this guide describes something I couldn't verify against source code, it says so, and
gives you a way to check it yourself.

---

## Contents

1. [The whole pipeline at a glance](#1-the-whole-pipeline-at-a-glance)
2. [Step 1: WebRTC transport](#2-step-1-webrtc-transport)
3. [Digital audio basics](#3-digital-audio-basics)
4. [Loudness: RMS and decibels](#4-loudness-rms-and-decibels)
5. [Step 2a: resampling 48 kHz stereo → 16 kHz mono](#5-step-2a-resampling-48-khz-stereo--16-khz-mono)
6. [Step 2b: Silero VAD, inside the model](#6-step-2b-silero-vad-inside-the-model)
7. [Step 3: endpointing](#7-step-3-endpointing)
8. [Roadmap: steps 4–10](#8-roadmap-steps-410)

---

## 1. The whole pipeline at a glance

```
Browser mic
  │ Opus-encoded packets, 20 ms each                          [code: WebRTC]
  ▼
aiortc decodes → 960 samples × 2 ch, int16, 48 kHz           [code + codec]
  │
  ▼ MonoResampler                                             [equation]
  │   average L/R → low-pass filter → keep 1 sample in 3
  ▼ 16 kHz mono, ~320 samples per frame
  │
  ▼ ÷ 32768 → float32 in -1…1                                 [equation]
  │
  ▼ buffer into 512-sample (32 ms) windows                    [code]
  │
  ▼ Silero VAD → P(speech) per window                         [model]
  │
  ▼ Endpointer → SPEECH START / SPEECH END / blip             [code + equation]
  │
  ▼ utterance .wav  ── step 4 ──▶ STT ──▶ LLM ──▶ TTS ──▶ back to browser
```

---

## 2. Step 1: WebRTC transport

**Kind: code.** No maths or models, just protocols. Real logs:
`release_notes/2026-09-28-phase4-step1-raw-audio-in.md`.

### Signaling: SDP offer and answer

Before any audio flows, the two sides have to agree on *what* they'll send and *how to reach
each other*. Each side writes this as an **SDP** (Session Description Protocol) text blob:

- which codecs it supports (e.g. Opus for audio),
- the network addresses it can be reached on (ICE candidates),
- encryption fingerprints (WebRTC media is always encrypted, using DTLS-SRTP).

The browser sends its SDP as an **offer** (`POST /offer`); aiortc replies with an **answer**.
This one HTTP exchange is the only time HTTP is involved.

### ICE: finding a path

Each side lists candidate addresses. ICE (Interactive Connectivity Establishment) then sends
small test packets for every pairing, local × remote, and the first pair to answer both ways
wins. In run 1, 8 local × 2 remote = 16 pairs were tried and one succeeded:
`172.17.211.55 (WSL) → 172.17.208.1 (Windows side of the WSL link)`.

### Opus and the frame format

- **Why 48 kHz, not the mic's own rate:** WebRTC uses the **Opus** codec, which runs at
  48 kHz internally, so aiortc decodes back to 48 kHz.
- **Why 20 ms frames:** Opus sends audio in 20 ms packets. At 48 kHz that's 960 samples.
- **Why stereo:** the browser sends two channels. A laptop mic is mono, so both are copies.

---

## 3. Digital audio basics

**Kind: equation.**

### Sampling

Sound is air pressure changing over time. A microphone turns it into a voltage, and an
analogue-to-digital converter measures that voltage at regular intervals. Each measurement is
a **sample**.

- **Sample rate `fs`:** samples per second. 48,000 Hz means one sample every 1/48000 s ≈ 20.8 µs.
- **Duration of N samples:** `t = N / fs`. So 960 / 48000 = 0.020 s = 20 ms.

### Bit depth and the int16 → float conversion

`s16` means each sample is a 16-bit signed integer, from −32,768 to +32,767. Silero was trained
on floats between −1 and 1, so we divide:

```
x_float = x_int16 / 32768
```

32,768 = 2¹⁵, the size of the negative half of the int16 range. The result lies in −1.0 to just
under +1.0.

### Interleaved stereo

Two channels in one row: `L0 R0 L1 R1 L2 R2 …`. That's why the first frame's array shape was
`(1, 1920)`: 960 samples × 2 channels.

---

## 4. Loudness: RMS and decibels

**Kind: equation.**

### RMS (root mean square)

```
RMS = sqrt( (1/N) · Σ x[n]² )
```

1. Square every sample. Squaring makes negatives positive, so + and − swings don't cancel out.
2. Take the mean. That's the average energy per sample.
3. Take the square root to get back to the original units.

Your step 1 and 2 logs show RMS values in int16 units. Around 20–80 is a quiet room, and about
1,500–3,700 is normal speech close to the mic.

### Decibels (dBFS)

Loudness is usually expressed on a log scale, because hearing is roughly logarithmic:

```
dBFS = 20 · log10( RMS / 32768 )
```

"FS" means *full scale*: 0 dBFS is the loudest possible signal, and everything else is negative.

| RMS (int16) | dBFS |
|---|---|
| 32,768 | 0 dB (maximum) |
| 3,277 | −20 dB |
| 1,600 | ≈ −26 dB (your close speech) |
| 800 | ≈ −32 dB (your speech from further away) |
| 50 | ≈ −56 dB (quiet room) |

### Why distance halved your RMS

In open air, sound pressure falls off roughly with **1/distance**. Doubling the distance halves
the pressure amplitude:

```
20 · log10(1/2) ≈ −6 dB per doubling of distance
```

In step 2 your RMS went from about 1,600 close up to about 800 further away, which is −6 dB,
consistent with doubling the distance. In a real room, reflections off walls and the browser's
automatic gain control (`autoGainControl: true`) blur this, so treat it as approximate.

---

## 5. Step 2a: resampling 48 kHz stereo → 16 kHz mono

**Kind: equation** (done inside ffmpeg's `libswresample`, called through PyAV). Real logs:
`release_notes/2026-09-28-phase4-step2-resample-and-vad.md`.

### Stereo → mono

```
mono[n] = ( left[n] + right[n] ) / 2
```

### The Nyquist limit

A signal sampled at rate `fs` can only represent frequencies up to **fs / 2**, the *Nyquist
frequency*.

| Sample rate | Highest frequency it can hold |
|---|---|
| 48 kHz | 24 kHz (beyond human hearing, ~20 kHz) |
| 16 kHz | 8 kHz |
| 8 kHz (phone audio) | 4 kHz |

### Aliasing: why you can't just drop samples

If a frequency above the Nyquist limit is still in the signal when you reduce the sample rate,
it doesn't disappear. It *folds back* and shows up as a false lower frequency:

```
f_alias = | f − k · fs_new |   (for the integer k that puts the result between 0 and fs_new/2)
```

**Worked example:** a 10 kHz tone (say, a hiss or a sharp "s"), resampled to 16 kHz without
filtering: `|10 − 16| = 6 kHz`. The model would hear a 6 kHz tone that was never in the
original sound. That's aliasing: real high-frequency sound turning into fake mid-frequency
sound.

### The fix: low-pass filter, then decimate

1. **Low-pass filter** below 8 kHz, so there's nothing above the new Nyquist limit left to fold
   back.
2. **Decimate** by 48000 / 16000 = 3: keep every third sample.

A digital low-pass filter is a **convolution**: each output sample is a weighted sum of nearby
input samples.

```
y[n] = Σ_k  h[k] · x[n − k]
```

`h` is the filter's *impulse response*, its list of weights. The mathematically ideal low-pass
filter has a **sinc** shape:

```
h[k] = sinc(2 · fc · k / fs),     sinc(x) = sin(πx) / (πx)
```

An ideal sinc is infinitely long, so real resamplers cut it short and taper the ends with a
*window* function. This is a **windowed-sinc filter**. Filtering and decimating together:

```
y[m] = Σ_k  h[k] · x[3m − k]        (compute only the samples we keep)
```

Computing only the kept samples is what efficient resamplers do: there's no point filtering
samples that are about to be thrown away. ffmpeg's resampler uses a windowed-sinc design by
default. I haven't checked its exact filter length and window type, so read its documentation
if you need them.

### Why your first frame was 304 samples, not 320

A convolution needs samples on *both sides* of the output point, so the filter must wait for a
few input samples before producing output. That delay is the filter's **latency**. The first
frame lost 16 output samples to it; later frames catch up. This is why `audio.py` buffers
instead of assuming a fixed frame size.

### Why 16 kHz is enough for speech

- **Pitch:** a voice's fundamental frequency is roughly 85–255 Hz.
- **Formants:** the resonances that distinguish vowels are roughly 300–3,500 Hz.
- **Consonants:** most of the energy that makes sounds like "s" and "f" intelligible sits below
  about 8 kHz.

So 16 kHz, which holds everything up to 8 kHz, keeps almost everything speech recognition
needs. Phone audio at 8 kHz (holding up to 4 kHz) loses some of those consonant cues, which is
what Phase 1's audio lab compared.

---

## 6. Step 2b: Silero VAD, inside the model

**Kind: model.** Real logs: `release_notes/2026-09-28-phase4-step2-resample-and-vad.md`.

**How confident this section is:** the maths of each building block (Fourier transform,
convolution, LSTM, sigmoid) is standard and certain. The exact layer sizes of the Silero
version you're running are *not* verified here. Silero publishes its model as a compiled file,
and its internals have changed between versions. To see the real structure of the model your
code loads, run:

```python
import torch
model, _ = torch.hub.load("snakers4/silero-vad", "silero_vad", trust_repo=True)
print(model)                                          # the layer structure
print(sum(p.numel() for p in model.parameters()))     # number of learned weights
```

### What goes in and what comes out

- **In:** 512 samples of 16 kHz audio, 32 ms, as floats in −1…1.
- **Out:** one number between 0 and 1, the probability that the window contains speech.
- **Memory:** a hidden state carried from one window to the next. That's why it has
  `reset_states()`, and why one instance can't serve two calls at once.

### Stage 1: from samples to frequencies (Fourier transform)

A raw waveform is hard to reason about directly. What matters for speech is *which frequencies*
are present. The **Discrete Fourier Transform** converts N samples into N frequency
components:

```
X[k] = Σ_{n=0}^{N-1}  x[n] · w[n] · e^( −j·2π·k·n / N )
```

- `k` is the frequency bin. Bin `k` corresponds to `k · fs / N` Hz.
- `w[n]` is a window function that tapers the edges of the chunk, to avoid artificial jumps.
- `|X[k]|` (the magnitude) says *how much* of that frequency is present.

Doing this on short overlapping chunks, one after another, gives a **spectrogram**: frequency
content over time. This is the same picture Phase 1's audio lab drew. Speech models, Silero
included, work from a representation like this rather than raw samples, and Silero computes its
frequency analysis inside the network itself.

**What speech looks like in a spectrogram:**

- **Harmonics:** voiced sounds (vowels, "m", "n") have a pitch `f0` and energy at every whole
  multiple of it: `f0, 2·f0, 3·f0, …`. On a spectrogram that's a stack of evenly spaced
  horizontal lines, like a comb.
- **Formants:** broad bands of extra energy, set by the shape of the mouth and throat. Their
  positions move as vowels change.
- **Rhythm:** energy rises and falls about 4–5 times a second, once per syllable.

For comparison, a fan is a flat smear across all frequencies, a clap is a short vertical burst
with no harmonic lines, and a keyboard click is a thin vertical spike.

### Stage 2: pattern detection (convolution layers)

A 1-D convolution slides a small set of learned weights along the frequency/time
representation:

```
out[t] = ReLU( b + Σ_i  w[i] · in[t + i] )
```

`ReLU(z) = max(0, z)`: it keeps positive responses and zeroes out negative ones. Unlike the
resampling filter in section 5, whose weights `h` came from a formula, these weights `w` were
**learned from data**. Early layers learn simple patterns, like "energy rising here". Deeper
layers combine them into more complex patterns, like "harmonic stack with a formant moving".

### Stage 3: memory across windows (LSTM)

A single 32 ms window is short. Whether it's speech depends partly on what came just before.
An **LSTM** (Long Short-Term Memory) is a recurrent layer that carries a hidden state `h` and a
cell state `c` from one step to the next. At each window `t`, with input `x_t`:

```
f_t = σ( W_f · [h_{t-1}, x_t] + b_f )        forget gate:  how much old memory to keep
i_t = σ( W_i · [h_{t-1}, x_t] + b_i )        input gate:   how much new information to add
g_t = tanh( W_g · [h_{t-1}, x_t] + b_g )     candidate new information
c_t = f_t ⊙ c_{t-1} + i_t ⊙ g_t              updated cell state (long-term memory)
o_t = σ( W_o · [h_{t-1}, x_t] + b_o )        output gate
h_t = o_t ⊙ tanh(c_t)                        new hidden state (what's passed on)
```

`⊙` means element-wise multiplication. The gates are numbers between 0 and 1 that act like
dimmer switches on the memory. `h` and `c` are the "state" that `reset_states()` clears at the
start of each call.

This memory is why Silero can hold a high probability through a brief dip within a word, and
why it drops smoothly rather than instantly when speech stops.

### Stage 4: the probability (sigmoid)

The final layer produces one raw number `z` (called a *logit*), which could be any real
number. The **sigmoid** squashes it into 0…1:

```
σ(z) = 1 / (1 + e^(−z))
```

| z | σ(z) |
|---|---|
| −5 | 0.007 |
| 0 | 0.5 |
| +5 | 0.993 |

That's the `vad_max` number in your step 2 logs. A value of 0.5 means `z = 0`: the model is
exactly undecided.

### How it learned

The weights (every `w`, `W` and `b` above) were set by **training**:

1. Feed the network millions of labelled audio clips, each marked speech or not speech.
2. Compare its output probability to the label using a loss function (for yes/no labels,
   typically *binary cross-entropy*):

   ```
   loss = −[ y · log(p) + (1 − y) · log(1 − p) ]
   ```

   `y` is the true label (1 = speech, 0 = not) and `p` is the model's probability. The loss is
   near 0 when `p` matches `y`, and grows large when the model is confidently wrong.
3. Nudge every weight slightly in the direction that reduces the loss (*gradient descent*).
4. Repeat until the model is reliably right.

Silero did this for us, which is why the project uses the model as-is and doesn't train it:
"use open-source models, don't train from scratch."

---

## 7. Step 3: endpointing

**Kind: code + equation.** No model. Real logs:
`release_notes/2026-09-28-phase4-step3-endpointing.md`.

### Time is measured in windows

```
window length   = 512 / 16000 = 0.032 s = 32 ms
windows needed  = ceil( setting_ms / 32 )
actual duration = windows_needed × 32 ms
```

| Setting | ÷ 32 | Rounded up | Actual |
|---|---|---|---|
| `MIN_SPEECH_MS` 250 | 7.81 | 8 windows | 256 ms |
| `MIN_SILENCE_MS` 700 | 21.9 | 22 windows | **704 ms** (seen in run 1's log) |
| `PRE_ROLL_MS` 300 | 9.38 | 10 windows | 320 ms |
| tail 100 | 3.13 | 4 windows | 128 ms |

### Windows per second

```
16000 samples/s ÷ 512 samples/window = 31.25 windows/s
```

That's why step 2's logs alternated between 31 and 32 windows per second: the extra quarter
window builds up, and every fourth second gets one more.

### The state machine

```
             p ≥ START (0.50) for ≥ MIN_SPEECH (8 windows)
   SILENT ─────────────────────────────────────────────────▶ SPEAKING
          ◀─────────────────────────────────────────────────
             p < END (0.35) for ≥ MIN_SILENCE (22 windows)
```

**Hysteresis** means using two different thresholds, one for switching on and one for
switching off:

```
SILENT   → SPEAKING   needs  p ≥ 0.50
SPEAKING → SILENT     needs  p < 0.35 (sustained)
```

A value of 0.48 is below the "on" bar, but above the "off" bar. Once speaking, it keeps you
speaking; while silent, it doesn't start speech. Without the gap, a probability bouncing
around 0.5 would flip the state on and off every window. The same idea is used in
thermostats: heat on at 19 °C, off at 21 °C, so the heater doesn't click on and off constantly.

### Back-dated timestamps

```
START time = (index of first speech window)     × 32 ms   ← when speech began
END time   = (index where the silence began)    × 32 ms   ← when the caller went quiet

START detected at: START time + MIN_SPEECH   (≈ +256 ms)
END   detected at: END time   + MIN_SILENCE  (≈ +704 ms)
```

Run 1 confirmed this from wall-clock timestamps alone: a 3.46 s turn in audio time showed up
as 3.98 s between the log lines, a 0.52 s difference, close to 704 − 256 = 448 ms plus
processing and network jitter.

### The latency trade-off

```
time before the agent may reply ≥ MIN_SILENCE_MS
```

| Setting | Effect |
|---|---|
| Short (300 ms) | Replies fast, but cuts callers off when they pause to think |
| Long (1,500 ms) | Never cuts off, but every reply feels slow |

The plan's target for this stage is 200–500 ms. A silence timer alone can't reach that without
cutting people off. That's what *semantic* turn detection (a later step) is for: it also looks
at the *words* ("I'd like a…" isn't finished; "a table for two" probably is).

### Pre-roll: a ring buffer

Speech is only confirmed 8 windows after it starts, so the endpointer keeps the last 10 windows
of audio in a **ring buffer**: a fixed-size queue where adding a new item pushes out the oldest
(`collections.deque(maxlen=10)`). When speech is confirmed, those 10 windows are prepended, so
speech-to-text gets the first syllable too.

---

## 8. Roadmap: steps 4–10

Not built yet. This is what each remaining step will add, and what kind of thing it is.

| Step | Adds | Kind | Inside it |
|---|---|---|---|
| 4 | Speech-to-text (Groq Whisper) | **Model** (hosted) | Whisper is an encoder–decoder *transformer*. The audio becomes a **log-mel spectrogram** (the spectrogram from section 6, with frequencies squeezed onto the *mel scale*, which matches how humans hear pitch). The encoder reads it; the decoder writes text one token at a time |
| 5 | The agent's brain (Phase 3 `graph.py`, unchanged) | **Model** + code | The LLM plus your tools, already built and tested in Phase 3 |
| 6 | Text-to-speech (ElevenLabs) | **Model** (hosted) | A neural TTS model turns text into audio. ElevenLabs' internals are proprietary, so this project treats it as a black box |
| 7 | Speaking back over WebRTC | Code | An outgoing aiortc audio track that sends the TTS audio as 20 ms frames: the reverse of step 1 |
| 8 | Live log panel on the test page | Code | Events pushed from the server to the browser page |
| 9 | Barge-in | Code | If `SPEECH START` fires while the agent is talking: stop sending its audio, and cancel the reply in progress |
| 10 | Latency | Code + measurement | Time each stage; stream the LLM's first sentence to TTS so the agent starts speaking sooner |

**The mel scale** (for step 4):

```
mel(f) = 2595 · log10( 1 + f / 700 )
```

It stretches low frequencies and compresses high ones, the way human pitch perception does:
the difference between 200 Hz and 400 Hz sounds much bigger than between 7,200 Hz and
7,400 Hz. Whisper's input is a spectrogram whose frequency bins are spaced evenly on this
scale, with the log of the energy in each bin.

**Phase 4 is done when:** one table booking and one delivery order are completed by voice, in
English, and the agent can be interrupted cleanly.
