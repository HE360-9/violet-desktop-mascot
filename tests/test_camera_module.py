import unittest
from pathlib import Path
import shutil
import tempfile

import cv2
import numpy as np

from camera_module import (
    CameraWorker,
    MouthMotionDetector,
    detect_face,
    load_face_detectors,
    resolve_face_model_path,
)


class _FakeCascade:
    def __init__(self, normal=(), mirrored=()):
        self.normal = normal
        self.mirrored = mirrored

    def detectMultiScale(self, image, **_options):
        return self.mirrored if image[0, 0] else self.normal


class _FakeCv2:
    @staticmethod
    def flip(image, _axis):
        return image + 1


class FaceDetectionTests(unittest.TestCase):
    def test_frontal_detection_is_preferred_over_profile_fallback(self):
        frontal = _FakeCascade(normal=[(12, 8, 50, 50)])
        profile = _FakeCascade(normal=[(4, 5, 70, 70)])

        face, pose = detect_face(
            _FakeCv2, np.zeros((100, 120), dtype=np.uint8), [frontal], profile
        )

        self.assertEqual(tuple(face), (12, 8, 50, 50))
        self.assertEqual(pose, "frontal")

    def test_mirrored_profile_box_is_mapped_back_to_preview_coordinates(self):
        profile = _FakeCascade(mirrored=[(10, 7, 30, 32)])

        face, pose = detect_face(
            _FakeCv2, np.zeros((80, 120), dtype=np.uint8), [], profile
        )

        self.assertEqual(tuple(face), (80, 7, 30, 32))
        self.assertEqual(pose, "profile")

    def test_opencv_models_load_when_installed(self):
        frontal, profile = load_face_detectors(cv2)

        self.assertTrue(frontal)
        self.assertIsNotNone(profile)


class MouthMotionDetectorTests(unittest.TestCase):
    def test_face_cascade_loads_from_non_ascii_source_path(self):
        with tempfile.TemporaryDirectory(prefix="violet-camera-model-") as temp_dir:
            temp_root = Path(temp_dir)
            if any(ord(char) >= 128 for char in str(temp_root)):
                self.skipTest("A writable ASCII temporary path is required by OpenCV")
            source_dir = temp_root / "人脸模型"
            source_dir.mkdir()
            source = source_dir / "haarcascade_frontalface_default.xml"
            shutil.copyfile(
                Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml",
                source,
            )
            resolved = resolve_face_model_path(
                source,
                cache_roots=[temp_root / "ascii-cache"],
            )

            self.assertTrue(all(ord(char) < 128 for char in str(resolved)))
            self.assertFalse(cv2.CascadeClassifier(str(resolved)).empty())

    def test_frame_activity_is_normalized(self):
        before = np.zeros((24, 64), dtype=np.uint8)
        after = before.copy()
        after[:, :32] = 255

        self.assertAlmostEqual(CameraWorker._activity(cv2, before, after), 0.5)

    def test_sustained_mouth_motion_starts_and_silence_stops(self):
        detector = MouthMotionDetector()

        self.assertFalse(detector.update(0.08, 0.01, now=0.0))
        self.assertFalse(detector.update(0.08, 0.01, now=0.1))
        self.assertTrue(detector.update(0.08, 0.01, now=0.2))
        self.assertTrue(detector.update(0.0, 0.0, now=1.3))
        self.assertFalse(detector.update(0.0, 0.0, now=1.41))

    def test_control_region_motion_does_not_trigger_speech(self):
        detector = MouthMotionDetector()

        for now in (0.0, 0.1, 0.2, 0.3):
            self.assertFalse(detector.update(0.08, 0.08, now=now))

    def test_intermittent_motion_does_not_trigger_speech(self):
        detector = MouthMotionDetector()

        self.assertFalse(detector.update(0.08, 0.01, now=0.0))
        self.assertFalse(detector.update(0.0, 0.0, now=0.6))
        self.assertFalse(detector.update(0.08, 0.01, now=1.1))


if __name__ == "__main__":
    unittest.main()
