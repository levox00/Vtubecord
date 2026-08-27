# Vtubecord updater

`VtubecordUpdater.exe` checks the latest GitHub release, chooses the x64
Windows installer, verifies GitHub's SHA-256 asset digest when available, and
launches the installer without opening a terminal.

Configure the repository with either:

```text
update-config.json: { "repository": "owner/repository", "current_version": "0.1.0" }
VTUBECORD_GITHUB_REPOSITORY=owner/repository
```

The official repository (`levox00/Vtubecord`) is built in, so a packaged
updater works without an adjacent configuration file. The options above are
available when testing a fork or a private release repository.

The updater is intentionally separate from the main app so it can replace a
running installation safely after Vtubecord is closed.
