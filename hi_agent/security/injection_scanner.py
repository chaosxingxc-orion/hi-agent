"""
Prompt Injection Scanner for hi-agent.

Scans text content for prompt injection patterns before it is ingested
into the knowledge base or skill system. Detected content is blocked
and a SecurityEvent is emitted.

Detection categories:
  1. Invisible Unicode characters (zero-width, control chars, RTL overrides)
  2. Instruction override phrases ("ignore previous instructions", etc.)
  3. Credential exfiltration patterns (curl $API_KEY, Authorization headers)
  4. Hidden HTML elements (<div style="display:none">, etc.)
  5. Jailbreak attempt patterns

Inspired by Hermes Agent's prompt injection prevention.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import TYPE_CHECKING


# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------

class SecurityEventSeverity(StrEnum):
    """Severity levels for security events, ordered from lowest to highest."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def _rank(self) -> int:
        """Numeric rank for comparison (higher = more severe)."""
        return {"low": 0, "medium": 1, "high": 2, "critical": 3}[self.value]

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, SecurityEventSeverity):
            return NotImplemented
        return self._rank >= other._rank

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, SecurityEventSeverity):
            return NotImplemented
        return self._rank > other._rank

    def __le__(self, other: object) -> bool:
        if not isinstance(other, SecurityEventSeverity):
            return NotImplemented
        return self._rank <= other._rank

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SecurityEventSeverity):
            return NotImplemented
        return self._rank < other._rank


# ---------------------------------------------------------------------------
# InjectionPattern
# ---------------------------------------------------------------------------

@dataclass
class InjectionPattern:
    """A single detection rule for prompt injection scanning."""

    name: str
    """Human-readable identifier for this pattern."""

    pattern: str
    """Raw regular expression string."""

    severity: SecurityEventSeverity
    """How dangerous a match of this pattern is."""

    description: str
    """What this pattern detects and why it is dangerous."""

    category: str
    """One of: invisible_unicode | override | exfil | hidden_html | jailbreak."""


# ---------------------------------------------------------------------------
# Built-in patterns
# ---------------------------------------------------------------------------

BUILTIN_PATTERNS: list[InjectionPattern] = [
    InjectionPattern(
        name="zero_width_chars",
        pattern=r"[\u200b\u200c\u200d\u2060\ufeff\u00ad\u034f\u115f\u1160]",
        severity=SecurityEventSeverity.HIGH,
        description=(
            "Zero-width and invisible Unicode characters used to hide malicious "
            "content from human readers while remaining visible to language models."
        ),
        category="invisible_unicode",
    ),
    InjectionPattern(
        name="instruction_override",
        pattern=(
            r"(?i)(ignore\s+(all\s+)?(previous|prior|above)\s+instructions?"
            r"|disregard\s+your\s+(previous\s+)?instructions?"
            r"|system\s+prompt\s+override"
            r"|you\s+are\s+now\s+in\s+(developer|DAN|jailbreak)\s+mode)"
        ),
        severity=SecurityEventSeverity.CRITICAL,
        description=(
            "Phrases designed to override or nullify the system prompt and prior "
            "instructions given to the language model."
        ),
        category="override",
    ),
    InjectionPattern(
        name="credential_exfiltration",
        pattern=(
            r"(?i)(curl\s+.*\$[A-Z_]{3,}_?(KEY|TOKEN|SECRET|PASSWORD)"
            r"|Authorization:\s*Bearer\s*\$"
            r"|wget\s+.*\$[A-Z_]+)"
        ),
        severity=SecurityEventSeverity.CRITICAL,
        description=(
            "Shell commands or HTTP headers that attempt to exfiltrate API keys, "
            "tokens, secrets, or passwords from the execution environment."
        ),
        category="exfil",
    ),
    InjectionPattern(
        name="hidden_html_element",
        pattern=r'(?i)<(div|span|p|section)\s+[^>]*style\s*=\s*["\'][^"\']*display\s*:\s*none',
        severity=SecurityEventSeverity.MEDIUM,
        description=(
            "HTML elements with display:none that hide content from human readers "
            "while the content remains accessible to automated parsers and LLMs."
        ),
        category="hidden_html",
    ),
    InjectionPattern(
        name="rtl_override_chars",
        pattern=r"[\u202a-\u202e\u2066-\u2069]",
        severity=SecurityEventSeverity.HIGH,
        description=(
            "Unicode bidirectional control characters (RTL/LTR overrides and isolates) "
            "that can visually reverse or hide text to deceive human reviewers."
        ),
        category="invisible_unicode",
    ),
    InjectionPattern(
        name="jailbreak_phrases",
        pattern=(
            r"(?i)(you\s+are\s+DAN"
            r"|do\s+anything\s+now"
            r"|pretend\s+you\s+(have\s+no\s+)?(restrictions?|guidelines?)"
            r"|act\s+as\s+(an?\s+)?(unrestricted|uncensored)\s+(AI|assistant|model))"
        ),
        severity=SecurityEventSeverity.HIGH,
        description=(
            "Known jailbreak phrases that attempt to convince the model to bypass "
            "safety guidelines and content policies."
        ),
        category="jailbreak",
    ),
]


# ---------------------------------------------------------------------------
# ScanResult
# ---------------------------------------------------------------------------

_CONTENT_LOG_LIMIT = 200


@dataclass
class ScanResult:
    """Result of scanning a single piece of content."""

    content: str
    """Original content, truncated to 200 chars for logging."""

    blocked: bool
    """True when the highest matched severity meets or exceeds the block threshold."""

    matched_patterns: list[InjectionPattern]
    """All patterns that matched against the content."""

    severity: SecurityEventSeverity
    """Highest severity among matched patterns; LOW when no matches found."""

    source: str
    """Identifier for where the content originated (file path, URL, etc.)."""

    scanned_at: str
    """ISO 8601 timestamp of when the scan was performed."""

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-compatible dictionary."""
        return {
            "content_preview": self.content[:_CONTENT_LOG_LIMIT],
            "blocked": self.blocked,
            "matched_patterns": [
                {
                    "name": p.name,
                    "severity": p.severity,
                    "category": p.category,
                    "description": p.description,
                }
                for p in self.matched_patterns
            ],
            "severity": self.severity,
            "source": self.source,
            "scanned_at": self.scanned_at,
        }

    def summary(self) -> str:
        """Return a single-line summary suitable for log output."""
        pattern_names = ", ".join(p.name for p in self.matched_patterns) or "none"
        status = "BLOCKED" if self.blocked else "allowed"
        return (
            f"[{status}] source={self.source!r} severity={self.severity} "
            f"matches=[{pattern_names}] scanned_at={self.scanned_at}"
        )


# ---------------------------------------------------------------------------
# SecurityEvent
# ---------------------------------------------------------------------------

@dataclass
class SecurityEvent:
    """A structured security event produced after a scan."""

    event_id: str
    """UUID4 string identifying this specific event."""

    scan_result: ScanResult
    """The underlying scan result that triggered this event."""

    action_taken: str
    """One of: 'blocked' | 'allowed' | 'warned'."""

    created_at: str
    """ISO 8601 timestamp of when this event was created."""

    def to_dict(self) -> dict[str, object]:
        """Serialise to a JSON-compatible dictionary."""
        return {
            "event_id": self.event_id,
            "action_taken": self.action_taken,
            "created_at": self.created_at,
            "scan_result": self.scan_result.to_dict(),
        }


# ---------------------------------------------------------------------------
# InjectionDetectedError
# ---------------------------------------------------------------------------

class InjectionDetectedError(Exception):
    """Raised by InjectionScanner.scan_and_raise() when content is blocked."""

    def __init__(self, scan_result: ScanResult) -> None:
        self.scan_result = scan_result
        super().__init__(str(self))

    def __str__(self) -> str:
        return self.scan_result.summary()


# ---------------------------------------------------------------------------
# InjectionScanner
# ---------------------------------------------------------------------------

class InjectionScanner:
    """Scans text for prompt injection patterns before ingestion.

    All regular expressions are compiled once at construction time to avoid
    repeated compilation overhead during high-frequency scanning.

    Args:
        patterns: Custom list of InjectionPattern objects to use instead of the
            built-in patterns. Pass None to use BUILTIN_PATTERNS.
        block_on_severity: Minimum severity that causes a scan result to be
            marked as blocked. Defaults to MEDIUM.
    """

    def __init__(
        self,
        patterns: list[InjectionPattern] | None = None,
        block_on_severity: SecurityEventSeverity = SecurityEventSeverity.MEDIUM,
    ) -> None:
        self._block_on_severity = block_on_severity
        self._patterns: list[InjectionPattern] = list(
            patterns if patterns is not None else BUILTIN_PATTERNS
        )
        # Pre-compile all patterns exactly once at construction time.
        self._compiled: list[tuple[InjectionPattern, re.Pattern[str]]] = [
            (p, re.compile(p.pattern)) for p in self._patterns
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan(self, content: str, source: str = "") -> ScanResult:
        """Scan *content* against all registered patterns.

        Args:
            content: The raw text to inspect.
            source: An identifier for where the content came from
                (e.g. a file path or URL), used for logging.

        Returns:
            A ScanResult describing what was found and whether the
            content should be blocked.
        """
        matched: list[InjectionPattern] = []
        for pattern, compiled in self._compiled:
            if compiled.search(content):
                matched.append(pattern)

        # Determine the highest severity among all matches.
        if matched:
            highest = max(matched, key=lambda p: p.severity._rank).severity
        else:
            highest = SecurityEventSeverity.LOW

        blocked = bool(matched) and highest >= self._block_on_severity

        return ScanResult(
            content=content[:_CONTENT_LOG_LIMIT],
            blocked=blocked,
            matched_patterns=matched,
            severity=highest,
            source=source,
            scanned_at=datetime.now(tz=timezone.utc).isoformat(),
        )

    def scan_and_raise(self, content: str, source: str = "") -> None:
        """Scan content and raise InjectionDetectedError if it is blocked.

        Args:
            content: The raw text to inspect.
            source: An identifier for where the content came from.

        Raises:
            InjectionDetectedError: When the scan result is blocked.
        """
        result = self.scan(content, source=source)
        if result.blocked:
            raise InjectionDetectedError(result)

    def create_security_event(self, result: ScanResult) -> SecurityEvent:
        """Wrap a ScanResult in a SecurityEvent for audit logging.

        Args:
            result: A previously obtained ScanResult.

        Returns:
            A SecurityEvent with a freshly generated event_id and
            action_taken set to 'blocked' or 'allowed'.
        """
        action = "blocked" if result.blocked else "allowed"
        return SecurityEvent(
            event_id=str(uuid.uuid4()),
            scan_result=result,
            action_taken=action,
            created_at=datetime.now(tz=timezone.utc).isoformat(),
        )

    def add_pattern(self, pattern: InjectionPattern) -> None:
        """Register an additional detection pattern at runtime.

        The pattern's regular expression is compiled immediately and stored
        alongside the pre-compiled built-in patterns.

        Args:
            pattern: The new InjectionPattern to add.
        """
        self._patterns.append(pattern)
        self._compiled.append((pattern, re.compile(pattern.pattern)))
