"""Proactive notification system for Foxhound.

Routes notifications to desktop, SMS, email, web push, and Slack channels
based on configurable policy and user preferences.
"""

from foxhound.notifications.channels.base import BaseNotificationChannel, Notification
from foxhound.notifications.dispatch import NotificationDispatch
from foxhound.notifications.policy import NotificationPolicy

__all__ = [
    "BaseNotificationChannel",
    "Notification",
    "NotificationDispatch",
    "NotificationPolicy",
]
