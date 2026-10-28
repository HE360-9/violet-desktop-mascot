import subprocess
import sys
import unittest

from process_utils import stop_process_tree


class StopProcessTreeTests(unittest.TestCase):
    def test_stops_a_running_process(self):
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"]
        )
        self.addCleanup(stop_process_tree, process)

        stop_process_tree(process)

        self.assertIsNotNone(process.poll())


if __name__ == "__main__":
    unittest.main()
