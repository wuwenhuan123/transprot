from __future__ import annotations


class AutoTranslateState:
    def __init__(self, stable_duration_ms: int = 800) -> None:
        self._stable_duration_ms = stable_duration_ms
        self._last_success_source_text: str | None = None
        self.reset(retain_success_source_text=True)

    @property
    def last_success_source_text(self) -> str | None:
        return self._last_success_source_text

    def observe(self, fingerprint: str, now_ms: int) -> bool:
        if self._inflight_fingerprint is not None:
            return False
        if fingerprint != self._observed_fingerprint:
            self._observed_fingerprint = fingerprint
            self._observed_since_ms = now_ms
            return False
        if fingerprint == self._last_processed_fingerprint:
            return False
        if self._observed_since_ms is None:
            self._observed_since_ms = now_ms
            return False
        if now_ms - self._observed_since_ms < self._stable_duration_ms:
            return False
        self._inflight_fingerprint = fingerprint
        return True

    def mark_attempt_finished(self, fingerprint: str | None) -> None:
        self._inflight_fingerprint = None
        if fingerprint:
            self._last_processed_fingerprint = fingerprint

    def mark_success_source_text(self, normalized_text: str | None) -> None:
        self._last_success_source_text = normalized_text or None

    def suppress_current_fingerprint(self, fingerprint: str | None) -> None:
        self._inflight_fingerprint = None
        self._observed_fingerprint = fingerprint
        self._observed_since_ms = None
        if fingerprint:
            self._last_processed_fingerprint = fingerprint

    def reset(self, retain_success_source_text: bool = False) -> None:
        self._observed_fingerprint: str | None = None
        self._observed_since_ms: int | None = None
        self._last_processed_fingerprint: str | None = None
        self._inflight_fingerprint: str | None = None
        if not retain_success_source_text:
            self._last_success_source_text = None
