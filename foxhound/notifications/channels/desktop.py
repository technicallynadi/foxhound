"""Desktop notification channel.

Uses osascript on macOS (built-in, no dependencies),
notify-send on Linux, and desktop-notifier as fallback.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from foxhound.notifications.channels.base import Notification

logger = logging.getLogger(__name__)


class DesktopNotificationChannel:
    """Sends OS-level desktop notifications."""

    def __init__(self) -> None:
        self._method: str | None = None

    def channel_name(self) -> str:
        return "desktop"

    def configure(self, config: dict) -> None:
        if sys.platform == "darwin":
            self._method = "osascript"
        elif sys.platform == "linux" and shutil.which("notify-send"):
            self._method = "notify-send"
        else:
            self._method = "desktop-notifier"

    async def send(self, notification: Notification) -> bool:
        """Send an OS-level desktop notification."""
        if self._method is None:
            return False
        try:
            if self._method == "osascript":
                return self._send_osascript(notification)
            elif self._method == "notify-send":
                return self._send_notify_send(notification)
            else:
                return await self._send_desktop_notifier(notification)
        except Exception as e:
            logger.warning("Desktop notification failed: %s", e)
            return False

    @staticmethod
    def _sanitize_for_applescript(text: str) -> str:
        """Sanitize text for safe use in AppleScript strings.

        Strips all characters that could break out of an AppleScript
        string context. Only allows printable ASCII and common unicode.
        """
        # Escape backslashes first, then double quotes
        text = text.replace("\\", "\\\\")
        text = text.replace('"', '\\"')
        # Strip any remaining control characters
        return "".join(c for c in text if c.isprintable())

    def _send_osascript(self, notification: Notification) -> bool:
        """macOS: use built-in osascript — no dependencies needed."""
        title = self._sanitize_for_applescript(notification.title[:100])
        body = self._sanitize_for_applescript(notification.body[:200])
        script = (
            f'display notification "{body}" '
            f'with title "Foxhound" '
            f'subtitle "{title}" '
            f'sound name "default"'
        )
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0

    @staticmethod
    def open_file(path: str) -> None:
        """Open a file in the user's editor. Call separately from send."""
        import shutil as _shutil

        if _shutil.which("code"):
            subprocess.Popen(["code", path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-t", path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sys.platform == "linux":
            subprocess.Popen(["xdg-open", path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _send_notify_send(self, notification: Notification) -> bool:
        """Linux: use notify-send CLI."""
        urgency = {
            "low": "low",
            "normal": "normal",
            "high": "critical",
            "critical": "critical",
        }.get(notification.priority, "normal")
        cmd = [
            "notify-send",
            "-a", "Foxhound",
            "-u", urgency,
            notification.title,
            notification.body,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=5)
        return result.returncode == 0

    async def _send_desktop_notifier(self, notification: Notification) -> bool:
        """Fallback: use desktop-notifier library."""
        try:
            from desktop_notifier import DesktopNotifier

            notifier = DesktopNotifier(app_name="Foxhound")
            await notifier.send(
                title=notification.title,
                message=notification.body,
            )
            return True
        except ImportError:
            logger.warning("No notification method available")
            return False
