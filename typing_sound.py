"""Short, locally generated keystroke sounds for the chat input."""

import math
import random
import struct
import tempfile
import wave
from pathlib import Path

from PyQt6.QtCore import QEvent, QObject, Qt, QUrl
from PyQt6.QtMultimedia import QSoundEffect


class TypingSound(QObject):
    """Play a quiet typewriter-like click for printable key presses."""

    _SAMPLE_RATE = 22050
    _VARIANTS = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self._temp_dir = tempfile.TemporaryDirectory(prefix="violet-typewriter-")
        self._effects = []
        for variant in range(self._VARIANTS):
            path = Path(self._temp_dir.name) / f"key-{variant}.wav"
            self._write_click(path, variant)
            effect = QSoundEffect(self)
            effect.setSource(QUrl.fromLocalFile(str(path)))
            effect.setVolume(0.14)
            self._effects.append(effect)
        self._next_effect = 0

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
            blocked = (
                Qt.KeyboardModifier.ControlModifier
                | Qt.KeyboardModifier.AltModifier
                | Qt.KeyboardModifier.MetaModifier
            )
            if (event.text() and not event.modifiers() & blocked
                    and any(char.isprintable() for char in event.text())):
                self._play()
        return False

    def _play(self):
        effect = self._effects[self._next_effect]
        self._next_effect = (self._next_effect + 1) % len(self._effects)
        effect.play()

    @classmethod
    def _write_click(cls, path: Path, variant: int):
        rng = random.Random(4171 + variant * 173)
        sample_count = int(cls._SAMPLE_RATE * 0.045)
        pcm = bytearray(sample_count * 2)
        high_tone = 1650 + variant * 190
        low_tone = 430 + variant * 55

        for index in range(sample_count):
            time = index / cls._SAMPLE_RATE
            noise = rng.uniform(-1.0, 1.0) * math.exp(-time / 0.0035) * 0.62
            click = math.sin(2 * math.pi * high_tone * time) * math.exp(-time / 0.008)
            body = math.sin(2 * math.pi * low_tone * time) * math.exp(-time / 0.018)
            sample = max(-1.0, min(1.0, (noise + click * 0.42 + body * 0.24) * 0.48))
            struct.pack_into("<h", pcm, index * 2, int(sample * 32767))

        with wave.open(str(path), "wb") as sound_file:
            sound_file.setnchannels(1)
            sound_file.setsampwidth(2)
            sound_file.setframerate(cls._SAMPLE_RATE)
            sound_file.writeframes(pcm)
