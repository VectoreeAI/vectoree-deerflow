"""Tie DeerFlow sessions to the visitor's current cloud preview project.

In ``DEPLOY_MODE=cloud`` users are scoped to one Vectoree project. A session
is valid only while the token's ``vp`` claim, the user's project and the
active preview's project all agree; reopening DeerFlow from another project's
Preview button therefore lands the visitor back on the login page.
"""

from __future__ import annotations

from deerflow.community.vectoree.credentials import bound_credentials, is_cloud_mode


def current_preview_project() -> str:
    """Project id of the preview bound to this request, or ``""``."""
    credentials = bound_credentials()
    return credentials.project_id if credentials is not None else ""


def user_matches_preview(user, *, token_project: str | None = None, preview_project: str | None = None) -> bool:
    """Whether ``user`` may act under the current preview.

    ``token_project`` is the session's ``vp`` claim; ``None`` skips the claim
    check for credentials that carry none (PATs). ``preview_project`` defaults
    to the preview bound by ``PreviewMiddleware``.
    """
    if not is_cloud_mode():
        return True
    project = current_preview_project() if preview_project is None else preview_project
    if not project or getattr(user, "vectoree_project_id", "") != project:
        return False
    return token_project is None or token_project == project
