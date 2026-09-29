"""
Audio format conversion: 48 kHz stereo (what WebRTC delivers) -> 16 kHz mono (what Silero
VAD and Whisper expect).

This is code, not a model. PyAV hands the work to ffmpeg's resampler, which does two
separate things:

  1. Stereo -> mono: averages the left and right channel of each sample pair.
  2. 48 kHz -> 16 kHz: keeps one sample in three - but not naively. A signal sampled at
     16 kHz can only represent frequencies up to 8 kHz (half the sample rate, the Nyquist
     limit). Anything above 8 kHz left in the audio would "fold back" and show up as false
     low-frequency sound (aliasing). So the resampler first applies a low-pass filter
     (an equation, applied to every sample) to remove it, then drops samples. Losing
     everything above 8 kHz is fine for speech: most of what makes words intelligible sits
     well below it - the same trade-off phone audio makes at 8 kHz, which Phase 1's audio
     lab compared directly.

Each 20 ms input frame of 960 samples x 2 channels becomes 320 mono samples.
"""

import av
import numpy as np

TARGET_SAMPLE_RATE = 16000


class MonoResampler:
    """One per audio track - the resampler keeps a little internal state (filter history
    from the previous frame), so frames from two different calls must not share one."""

    def __init__(self) -> None:
        self._resampler = av.AudioResampler(format="s16", layout="mono", rate=TARGET_SAMPLE_RATE)

    def __call__(self, frame: av.AudioFrame) -> np.ndarray:
        """Returns this frame's audio as a flat int16 array at 16 kHz mono. The resampler
        can hold samples back or release extra ones at the edges, so the length isn't
        always exactly 320 - callers should buffer, not assume a fixed size."""
        out_frames = self._resampler.resample(frame)
        if not out_frames:
            return np.zeros(0, dtype=np.int16)
        return np.concatenate([f.to_ndarray().reshape(-1) for f in out_frames])
