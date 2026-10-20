"""Local session cleanup for switching standalone EA accounts."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def default_webview_profile() -> Path:
    local_app_data = Path(os.environ["LOCALAPPDATA"]).resolve()
    return local_app_data / "EAStandaloneLauncher" / "WebView2"


def clear_standalone_session(
    *,
    token_store: Path,
    library_store: Path,
    summary_path: Path,
    webview_profile: Path | None = None,
) -> dict[str, bool]:
    """Remove account tokens, library data, and the remembered browser session."""
    profile = (webview_profile or default_webview_profile()).resolve()
    local_app_data = Path(os.environ["LOCALAPPDATA"]).resolve()
    expected_parent = local_app_data / "EAStandaloneLauncher"
    if profile.name != "WebView2" or profile.parent != expected_parent:
        raise ValueError(f"refusing to remove unexpected WebView profile path: {profile}")

    removed: dict[str, bool] = {}
    for label, path in (
        ("tokens", token_store),
        ("library", library_store),
        ("summary", summary_path),
    ):
        existed = path.exists()
        if existed:
            path.unlink()
        removed[label] = existed
    profile_existed = profile.exists()
    if profile_existed:
        shutil.rmtree(profile)
    removed["webview_profile"] = profile_existed
    return removed
