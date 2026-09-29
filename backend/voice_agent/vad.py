"""
Voice activity detection with Silero VAD - the first *model* in the pipeline.

Silero is a small neural network (~2 MB). Given 512 samples of 16 kHz audio (32 ms), it
returns a probability from 0 to 1 that someone is speaking in that window. Unlike RMS
loudness, it was trained on speech vs non-speech, so it looks at the shape of the sound
(its frequency pattern over time), not just its volume. A cough is loud but not speech;
a quiet word is speech but not loud.

It's also stateful: it remembers the previous windows (a recurrent network), which is why
it must be reset between calls and why one instance can't safely serve two calls at once.

Same model and loading call as Phase 1's audio lab (audio_lab/notebooks_or_scripts/
03_vad_silero.ipynb), already cached locally by that notebook.
"""

import numpy as np
import torch

from logger import logging

SAMPLE_RATE = 16000
WINDOW_SAMPLES = 512  # the only window size Silero accepts at 16 kHz = 32 ms


class SileroVAD:
    def __init__(self) -> None:
        # Silero's own recommendation: one thread is faster than many for a model this
        # small, since the overhead of splitting work across threads outweighs the work.
        torch.set_num_threads(1)
        self.model, _utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad", model="silero_vad", force_reload=False, trust_repo=True
        )
        self._buffer = np.zeros(0, dtype=np.float32)
        logging.info("Silero VAD loaded")

    def reset(self) -> None:
        """Call at the start of each new audio track."""
        self.model.reset_states()
        self._buffer = np.zeros(0, dtype=np.float32)

    def process(self, samples: np.ndarray) -> list[tuple[float, np.ndarray]]:
        """Feeds int16 16 kHz mono samples in. Returns one (speech probability, window
        audio) pair per complete 512-sample window. Leftover samples wait in the buffer
        for the next call - frames arrive as ~320 samples, which doesn't divide evenly
        into 512.

        The window audio comes back too (float32, -1.0..1.0) so the endpointer can collect
        exactly the audio each probability was computed from."""
        # Silero wants floats in -1.0..1.0, not int16's -32768..32767
        audio = samples.astype(np.float32) / 32768.0
        self._buffer = np.concatenate([self._buffer, audio])

        results = []
        while len(self._buffer) >= WINDOW_SAMPLES:
            window = self._buffer[:WINDOW_SAMPLES]
            self._buffer = self._buffer[WINDOW_SAMPLES:]
            with torch.no_grad():
                probability = float(self.model(torch.from_numpy(window), SAMPLE_RATE))
            results.append((probability, window))
        return results
