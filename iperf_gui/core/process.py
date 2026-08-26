"""Small cross-platform helpers for launching child processes."""

from __future__ import annotations

import os
import subprocess

#: Grace period given to a child process to exit after a terminate request
#: before it is killed outright.
TERMINATE_GRACE_SECONDS = 3.0


def creation_flags() -> int:
    """Flags preventing a console window from flashing up on Windows.

    ``CREATE_NO_WINDOW`` only exists in :mod:`subprocess` on Windows, so this
    resolves to ``0`` (no special behaviour) everywhere else.
    """
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def terminate_process(process: subprocess.Popen, grace: float = TERMINATE_GRACE_SECONDS) -> None:
    """Stop ``process``, escalating from terminate to kill if it does not exit.

    Safe to call on an already-dead process. Never raises: shutdown paths must
    not be able to fail, since they run from window-close handlers where an
    exception would leave the child orphaned.
    """
    if process.poll() is not None:
        return

    try:
        process.terminate()
    except OSError:
        return

    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            process.wait(timeout=grace)
        except (OSError, subprocess.TimeoutExpired):
            pass
