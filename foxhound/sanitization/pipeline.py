"""Sanitization pipeline for normalizing and cleaning worker outputs."""

import fnmatch
import re
from typing import Any

from pydantic import BaseModel, Field

from foxhound.core.models import TrustLevel
from foxhound.harness.worker_protocol import SanitizedOutput, WorkerOutput

# Patterns that indicate command injection or code execution attempts
DANGEROUS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\$\(.*\)"),           # command substitution $(...)
    re.compile(r"`[^`]+`"),            # backtick command substitution
    re.compile(r"\beval\s*\("),        # eval()
    re.compile(r"\bexec\s*\("),        # exec()
    re.compile(r"\bos\.system\s*\("),  # os.system()
    re.compile(r"\bsubprocess\.\w+\s*\("),  # subprocess calls
    re.compile(r";\s*rm\s"),           # chained rm commands
    re.compile(r"\|\s*sh\b"),          # pipe to shell
    re.compile(r"\|\s*bash\b"),        # pipe to bash
    re.compile(r">\s*/dev/"),          # redirect to device files
    re.compile(r"\bsudo\s"),           # sudo usage
    re.compile(r"\bcurl\s.*\|\s*sh"),  # curl pipe to shell
]

# File patterns that are always blocked from context packs
SENSITIVE_FILE_PATTERNS: list[str] = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa",
    "id_ed25519",
    "credentials.json",
    "secrets.yaml",
    "secrets.yml",
    "*.secret",
]

SENSITIVE_DIR_PATTERNS: list[str] = [
    ".ssh/",
    "secrets/",
    ".aws/",
    ".gcloud/",
]

# Patterns that look like secrets/tokens in output text
SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"(?:api[_-]?key|token|secret|password|passwd|credential)"
        r"\s*[:=]\s*['\"]?[\w\-\.]{8,}",
        re.IGNORECASE,
    ),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),       # OpenAI-style keys
    re.compile(r"ghp_[a-zA-Z0-9]{36,}"),       # GitHub PATs
    re.compile(r"AKIA[0-9A-Z]{16}"),           # AWS access keys
    re.compile(r"-----BEGIN [\w\s]+ KEY-----"), # PEM private keys
]


class SanitizationResult(BaseModel):
    """Detailed result of sanitization with metadata."""

    output: SanitizedOutput
    dangerous_patterns_found: list[str] = Field(default_factory=list)
    sensitive_files_blocked: list[str] = Field(default_factory=list)
    secrets_redacted: int = Field(default=0)
    trust_labels: dict[str, str] = Field(default_factory=dict)


def is_sensitive_path(path: str) -> bool:
    """Check if a file path matches sensitive file patterns."""
    from pathlib import PurePosixPath

    name = PurePosixPath(path).name

    for pattern in SENSITIVE_FILE_PATTERNS:
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(path, pattern):
            return True

    for dir_pattern in SENSITIVE_DIR_PATTERNS:
        normalized = dir_pattern.rstrip("/")
        if f"/{normalized}/" in f"/{path}/" or path.startswith(normalized):
            return True

    return False


def strip_dangerous_patterns(text: str) -> tuple[str, list[str]]:
    """Remove dangerous patterns from text.

    Args:
        text: Input text to sanitize.

    Returns:
        Tuple of (sanitized text, list of patterns found).
    """
    found: list[str] = []
    sanitized = text

    for pattern in DANGEROUS_PATTERNS:
        matches = pattern.findall(sanitized)
        if matches:
            for match in matches:
                found.append(f"Stripped pattern: {match[:80]}")
            sanitized = pattern.sub("[STRIPPED]", sanitized)

    return sanitized, found


def redact_secrets(text: str) -> tuple[str, int]:
    """Redact potential secrets and tokens from text.

    Args:
        text: Input text to scan for secrets.

    Returns:
        Tuple of (redacted text, count of redactions).
    """
    count = 0

    for pattern in SECRET_PATTERNS:
        matches = pattern.findall(text)
        if matches:
            count += len(matches)
            text = pattern.sub("[REDACTED]", text)

    return text, count


def sanitize_payload(
    payload: dict[str, Any],
    trust_level: TrustLevel = TrustLevel.SEMI_TRUSTED,
) -> tuple[dict[str, Any], list[str], int]:
    """Recursively sanitize a payload dictionary.

    Strips dangerous patterns and redacts secrets from all string values.

    Args:
        payload: Dictionary to sanitize.
        trust_level: Trust level of the content.

    Returns:
        Tuple of (sanitized dict, patterns found, secrets redacted count).
    """
    all_patterns: list[str] = []
    total_redactions = 0
    result: dict[str, Any] = {}

    for key, value in payload.items():
        if isinstance(value, str):
            sanitized, patterns = strip_dangerous_patterns(value)
            all_patterns.extend(patterns)
            sanitized, redactions = redact_secrets(sanitized)
            total_redactions += redactions
            result[key] = sanitized
        elif isinstance(value, dict):
            sub_result, sub_patterns, sub_redactions = sanitize_payload(value, trust_level)
            result[key] = sub_result
            all_patterns.extend(sub_patterns)
            total_redactions += sub_redactions
        elif isinstance(value, list):
            sanitized_list: list[Any] = []
            for item in value:
                if isinstance(item, str):
                    s, p = strip_dangerous_patterns(item)
                    all_patterns.extend(p)
                    s, r = redact_secrets(s)
                    total_redactions += r
                    sanitized_list.append(s)
                elif isinstance(item, dict):
                    sub_result, sub_patterns, sub_redactions = sanitize_payload(
                        item, trust_level
                    )
                    sanitized_list.append(sub_result)
                    all_patterns.extend(sub_patterns)
                    total_redactions += sub_redactions
                else:
                    sanitized_list.append(item)
            result[key] = sanitized_list
        else:
            result[key] = value

    return result, all_patterns, total_redactions


def filter_sensitive_files(files: list[str]) -> tuple[list[str], list[str]]:
    """Filter sensitive files from a file list.

    Args:
        files: List of file paths.

    Returns:
        Tuple of (allowed files, blocked files).
    """
    allowed: list[str] = []
    blocked: list[str] = []

    for path in files:
        if is_sensitive_path(path):
            blocked.append(path)
        else:
            allowed.append(path)

    return allowed, blocked


def apply_trust_labels(
    files: list[str],
    default_level: TrustLevel = TrustLevel.SEMI_TRUSTED,
) -> dict[str, str]:
    """Assign trust labels to files.

    All worker output files are semi-trusted by default. External content
    (URLs, external sources) would be untrusted but that's handled by
    the caller providing the appropriate trust level.

    Args:
        files: List of file paths.
        default_level: Default trust level for files.

    Returns:
        Dictionary mapping file paths to trust level strings.
    """
    return {path: default_level.value for path in files}


class SanitizationPipeline:
    """Pipeline that sanitizes worker output before evaluation.

    Applies in order:
    1. Filter sensitive files from outputs
    2. Strip dangerous patterns from payload
    3. Redact secrets from payload
    4. Apply trust labels
    """

    def __init__(
        self,
        trust_level: TrustLevel = TrustLevel.SEMI_TRUSTED,
    ) -> None:
        """Initialize the sanitization pipeline.

        Args:
            trust_level: Default trust level for content being sanitized.
        """
        self._trust_level = trust_level

    def sanitize(self, output: WorkerOutput) -> SanitizationResult:
        """Run the full sanitization pipeline on a worker output.

        Args:
            output: Raw worker output to sanitize.

        Returns:
            SanitizationResult with sanitized output and metadata.
        """
        # 1. Filter sensitive files
        allowed_files, blocked_files = filter_sensitive_files(output.files_changed)

        # 2. Sanitize payload (strip patterns + redact secrets)
        sanitized_payload, patterns_found, secrets_redacted = sanitize_payload(
            output.payload, self._trust_level
        )

        # 3. Build redaction log
        redactions: list[str] = []
        if blocked_files:
            redactions.append(f"Blocked {len(blocked_files)} sensitive file(s)")
        if patterns_found:
            redactions.extend(patterns_found)
        if secrets_redacted > 0:
            redactions.append(f"Redacted {secrets_redacted} potential secret(s)")

        # 4. Apply trust labels
        trust_labels = apply_trust_labels(allowed_files, self._trust_level)

        # 5. Build sanitized output
        sanitized = SanitizedOutput(
            payload=sanitized_payload,
            commands_run=output.commands_run,
            files_changed=allowed_files,
            cost=output.cost,
            artifact_paths=output.artifact_paths,
            redactions_applied=redactions,
        )

        return SanitizationResult(
            output=sanitized,
            dangerous_patterns_found=patterns_found,
            sensitive_files_blocked=blocked_files,
            secrets_redacted=secrets_redacted,
            trust_labels=trust_labels,
        )
