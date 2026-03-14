"""Repo-native work discovery.

Provides scanners and the DiscoveryWorker for finding actionable
work items in repository source code.
"""

from foxhound.discovery.scanners import (
    DependencyAlertScanner,
    ScannerRegistry,
    ScanResult,
    TodoScanner,
    scan_result_to_work_item,
)
from foxhound.discovery.worker import DiscoveryWorker

__all__ = [
    "DependencyAlertScanner",
    "DiscoveryWorker",
    "ScannerRegistry",
    "ScanResult",
    "TodoScanner",
    "scan_result_to_work_item",
]
