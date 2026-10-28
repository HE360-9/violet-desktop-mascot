import unittest
from unittest.mock import patch

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLineEdit

from typing_sound import TypingSound


class _FakeSoundEffect:
    instances = []

    def __init__(self, _parent=None):
        self.play_count = 0
        self.__class__.instances.append(self)

    def setSource(self, _source):
        pass

    def setVolume(self, _volume):
        pass

    def play(self):
        self.play_count += 1


class TypingSoundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        _FakeSoundEffect.instances = []
        self.effect_patch = patch("typing_sound.QSoundEffect", _FakeSoundEffect)
        self.effect_patch.start()
        self.edit = QLineEdit()
        self.sound = TypingSound(self.edit)
        self.addCleanup(self.sound._temp_dir.cleanup)
        self.edit.installEventFilter(self.sound)
        self.edit.show()
        self.edit.setFocus()
        self.app.processEvents()

    def tearDown(self):
        self.edit.close()
        self.effect_patch.stop()

    def test_printable_keys_play_clicks_but_editing_keys_do_not(self):
        QTest.keyClicks(self.edit, "hi!")
        QTest.keyClick(self.edit, Qt.Key.Key_Backspace)
        QTest.keyClick(self.edit, Qt.Key.Key_Return)
        QTest.keyClick(
            self.edit, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier
        )

        self.assertEqual(sum(effect.play_count for effect in self.sound._effects), 3)

    def test_auto_repeat_does_not_play_an_extra_click(self):
        from PyQt6.QtCore import QEvent
        from PyQt6.QtGui import QKeyEvent

        event = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_A,
            Qt.KeyboardModifier.NoModifier,
            "a",
            True,
            1,
        )
        self.sound.eventFilter(self.edit, event)

        self.assertEqual(sum(effect.play_count for effect in self.sound._effects), 0)


if __name__ == "__main__":
    unittest.main()
