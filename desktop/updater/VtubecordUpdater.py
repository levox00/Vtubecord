"""Small, terminal-free Windows updater for Vtubecord GitHub releases.

The updater intentionally uses only Python's standard library so it can be
packaged into a small one-file executable. It checks the latest GitHub release,
downloads the x64 installer, verifies GitHub's SHA-256 digest when available,
and launches the installer with no console window.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

APP_TITLE = "Vtubecord Updater"
DEFAULT_TIMEOUT = 30
# The official release repository. A command-line argument, environment
# variable, or sidecar config can still override this for development forks.
DEFAULT_REPOSITORY = "levox00/Vtubecord"


class UpdaterError(RuntimeError):
    pass


def show_message(message: str, *, error: bool = False) -> None:
    """Display a native Windows message box; never require a terminal."""

    if os.name == "nt":
        flags = 0x00000010 if error else 0x00000040  # MB_ICONERROR / MB_ICONINFORMATION
        ctypes.windll.user32.MessageBoxW(None, message, APP_TITLE, flags)
    else:  # pragma: no cover - useful when testing the script on Linux
        print(f"{APP_TITLE}: {message}")


def _config_candidates() -> list[Path]:
    executable_dir = Path(sys.executable).resolve().parent
    return [
        executable_dir / "update-config.json",
        executable_dir.parent / "update-config.json",
        Path.cwd() / "update-config.json",
    ]


def load_config() -> dict[str, Any]:
    for path in _config_candidates():
        try:
            if path.is_file():
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    return raw
        except (OSError, json.JSONDecodeError):
            continue
    return {}


def normalize_repository(value: str) -> str:
    value = value.strip().strip("/")
    value = re.sub(r"^https?://github\.com/", "", value, flags=re.IGNORECASE)
    value = value.removesuffix(".git").strip("/")
    if not re.fullmatch(r"[^/\s]+/[^/\s]+", value):
        raise UpdaterError("Set a GitHub repository as owner/name in update-config.json.")
    return value


def parse_version(value: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", value.removeprefix("v"))
    return tuple(int(item) for item in numbers) or (0,)


def fetch_json(url: str) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Vtubecord-Updater/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise UpdaterError(f"GitHub returned HTTP {error.code} while checking releases.") from error
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise UpdaterError(f"Could not reach GitHub: {error}") from error
    if not isinstance(payload, dict):
        raise UpdaterError("GitHub returned an invalid release response.")
    return payload


def choose_asset(release: dict[str, Any]) -> dict[str, Any]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise UpdaterError("The GitHub release has no downloadable assets.")
    candidates = [
        asset
        for asset in assets
        if isinstance(asset, dict)
        and isinstance(asset.get("name"), str)
        and re.search(r"Vtubecord.*(?:x64|amd64).*setup\.exe$", asset["name"], re.IGNORECASE)
    ]
    if not candidates:
        candidates = [
            asset
            for asset in assets
            if isinstance(asset, dict)
            and isinstance(asset.get("name"), str)
            and asset["name"].lower().endswith(".msi")
        ]
    if not candidates:
        raise UpdaterError("The latest release does not contain a Vtubecord Windows installer.")
    return candidates[0]


def download_asset(asset: dict[str, Any]) -> Path:
    name = Path(str(asset.get("name") or "Vtubecord-update.exe")).name
    destination_dir = Path(tempfile.gettempdir()) / "Vtubecord-update"
    destination_dir.mkdir(parents=True, exist_ok=True)
    partial = destination_dir / f"{name}.part"
    destination = destination_dir / name
    url = str(asset.get("browser_download_url") or "")
    if not url:
        raise UpdaterError("The selected GitHub release asset has no download URL.")

    request = Request(url, headers={"User-Agent": "Vtubecord-Updater/1.0"})
    digest = hashlib.sha256()
    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT) as response, partial.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        partial.unlink(missing_ok=True)
        raise UpdaterError(f"Could not download the Vtubecord update: {error}") from error

    expected = str(asset.get("digest") or "")
    if expected.lower().startswith("sha256:"):
        expected = expected.split(":", 1)[1].strip().lower()
        if digest.hexdigest().lower() != expected:
            partial.unlink(missing_ok=True)
            raise UpdaterError("The downloaded installer failed its SHA-256 verification.")
    partial.replace(destination)
    return destination


def launch_installer(path: Path) -> None:
    startup_info = None
    creation_flags = 0
    if os.name == "nt":
        startup_info = subprocess.STARTUPINFO()
        startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup_info.wShowWindow = 0
        creation_flags = 0x08000000  # CREATE_NO_WINDOW
    subprocess.Popen([str(path)], startupinfo=startup_info, creationflags=creation_flags)


def run(args: argparse.Namespace) -> int:
    config = load_config()
    repository = normalize_repository(
        args.repo
        or os.environ.get("VTUBECORD_GITHUB_REPOSITORY", "")
        or str(config.get("repository", ""))
        or DEFAULT_REPOSITORY
    )
    current = args.current_version or str(config.get("current_version", "0.0.0"))
    release = fetch_json(f"https://api.github.com/repos/{repository}/releases/latest")
    latest = str(release.get("tag_name") or release.get("name") or "")
    if not latest:
        raise UpdaterError("The GitHub release did not provide a version tag.")
    if parse_version(latest) <= parse_version(current):
        show_message(f"Vtubecord {current} is up to date (latest: {latest}).")
        return 0
    asset = choose_asset(release)
    if args.check_only:
        show_message(f"Vtubecord {latest} is available.")
        return 0
    show_message(f"Downloading Vtubecord {latest}. The installer will open when ready.")
    installer = download_asset(asset)
    launch_installer(installer)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--repo", help="GitHub owner/name, for example example/vtubecord")
    parser.add_argument("--current-version", help="Currently installed version")
    parser.add_argument("--check-only", action="store_true", help="Only check for an available release")
    args = parser.parse_args()
    try:
        return run(args)
    except UpdaterError as error:
        show_message(str(error), error=True)
        return 1
    except Exception as error:  # keep packaged updater failures user-visible
        show_message(f"Unexpected updater error: {error}", error=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
