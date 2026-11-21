import unittest

from usb_bridge import describe


class DescribeReadingTests(unittest.TestCase):
    def test_missing_sensor_fields_do_not_stop_bridge_output(self):
        reading = {
            "finger": True,
            "bpm_avg": 82.0,
            "gsr_contact": True,
        }

        message = describe(reading)

        self.assertIn("82.0 BPM", message)
        self.assertIn("gsr unavailable", message)
        self.assertIn("wrist change unavailable", message)


if __name__ == "__main__":
    unittest.main()
