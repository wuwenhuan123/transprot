from __future__ import annotations


class JobGuard:
    def __init__(self) -> None:
        self._current_job_id = 0

    def next_job(self) -> int:
        self._current_job_id += 1
        return self._current_job_id

    def is_current(self, job_id: int) -> bool:
        return job_id == self._current_job_id

