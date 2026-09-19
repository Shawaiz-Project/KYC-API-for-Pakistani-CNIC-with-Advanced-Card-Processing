"""Quarantined legacy camera prototype.

The original module opened the workstation camera and processed face landmarks
at import time. It was not part of any Django route, depended on an undeclared
MediaPipe installation, and contained runtime errors. Importing application
modules must never activate a camera or biometric processing, so the prototype
is deliberately non-operational until a separately designed, consent-aware
liveness phase supplies an explicit interface and security review.
"""

from __future__ import annotations


def run_legacy_head_pose_demo() -> None:
    """Refuse implicit biometric capture from the Phase 1 server package."""

    raise RuntimeError(
        "The legacy webcam prototype is disabled; Phase 1 does not implement liveness."
    )


if __name__ == "__main__":
    raise SystemExit(
        "The legacy webcam prototype is disabled; Phase 1 does not implement liveness."
    )
