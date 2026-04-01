from __future__ import annotations

import unittest

from transprot.core.job_guard import JobGuard


class JobGuardTests(unittest.TestCase):
    def test_only_latest_job_is_current(self) -> None:
        guard = JobGuard()
        first = guard.next_job()
        second = guard.next_job()
        self.assertFalse(guard.is_current(first))
        self.assertTrue(guard.is_current(second))


if __name__ == "__main__":
    unittest.main()
