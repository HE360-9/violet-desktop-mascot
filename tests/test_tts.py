import subprocess
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import core.tts as tts


class LoudnessNormalizationTests(unittest.TestCase):
    def test_ffmpeg_dll_startup_failure_is_retried_once(self):
        failed_run = subprocess.CompletedProcess(
            args=["ffmpeg"], returncode=3221225794, stdout=b"", stderr=b""
        )
        successful_run = subprocess.CompletedProcess(
            args=["ffmpeg"], returncode=0, stdout=b"", stderr=b""
        )

        with patch.object(
            tts.subprocess, "run", side_effect=[failed_run, successful_run]
        ) as run:
            result = tts._run_ffmpeg(["ffmpeg", "-version"])

        self.assertEqual(result.returncode, 0)
        self.assertEqual(run.call_count, 2)

    def test_ffmpeg_processes_are_serialized(self):
        active = 0
        max_active = 0
        state_lock = threading.Lock()

        def fake_run(*_args, **_kwargs):
            nonlocal active, max_active
            with state_lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.02)
            with state_lock:
                active -= 1
            return subprocess.CompletedProcess(args=[], returncode=0)

        with patch.object(tts.subprocess, "run", side_effect=fake_run):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: tts._run_ffmpeg(["ffmpeg"]), range(2)))

        self.assertEqual(max_active, 1)
        self.assertTrue(all(result.returncode == 0 for result in results))

    def test_ffmpeg_crash_preserves_audio_and_logs_windows_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "sample.wav"
            original_audio = b"original audio"
            audio_path.write_bytes(original_audio)
            failed_run = subprocess.CompletedProcess(
                args=["ffmpeg"], returncode=3221225794, stdout=b"", stderr=b""
            )

            with (
                patch.object(tts, "_measure_loudness", return_value=(-27.72, -10.0)),
                patch.object(tts, "_ffmpeg_exe", return_value="ffmpeg.exe"),
                patch.object(tts.subprocess, "run", side_effect=[failed_run, failed_run]),
                patch.object(tts, "_log") as log,
            ):
                result = tts.normalize_loudness(str(audio_path))

            self.assertEqual(result, str(audio_path))
            self.assertEqual(audio_path.read_bytes(), original_audio)
            message = " ".join(str(arg) for arg in log.call_args.args)
            self.assertIn("0xC0000142", message)
            self.assertIn("DLL initialization failed", message)


if __name__ == "__main__":
    unittest.main()
