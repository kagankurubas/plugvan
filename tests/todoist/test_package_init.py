"""
Tests for the plugvan.todoist package module: its logging setup must not run at import time.
"""

import os
import subprocess
import sys
from pathlib import Path


def test_importing_the_package_leaves_the_httpx_logger_alone():
    """Only configure_logging() sets the httpx level, never an import, so a program that imports
    plugvan.todoist keeps its own httpx configuration. Checked in a fresh process: this one has
    imported everything already."""
    probe = (
        "import logging, plugvan.todoist, plugvan.todoist.client, plugvan.todoist.server; "
        "print(logging.getLevelName(logging.getLogger('httpx').level))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).resolve().parents[2],
        env={name: value for name, value in os.environ.items() if name != "PYTHONPATH"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "NOTSET"
