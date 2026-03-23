#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import re
import shutil
import tarfile
import urllib.request


RELEASES_URL = "https://api.github.com/repos/defold/defold/releases?per_page=20"
ASSET_NAME = "Defold-x86_64-linux.tar.gz"


def fetch_json(url: str) -> object:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "editor-metrics/phase-1",
        },
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def download(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "editor-metrics/phase-1"})
    with urllib.request.urlopen(request) as response, dest.open("wb") as output:
        shutil.copyfileobj(response, output)


def choose_release(releases: list[dict[str, object]]) -> dict[str, object]:
    for release in releases:
        if release.get("target_commitish") != "dev":
            continue
        if not release.get("prerelease"):
            continue
        tag = str(release.get("tag_name", ""))
        if "alpha" not in tag:
            continue
        return release
    raise RuntimeError("could not find alpha release tracking dev")


def editor_sha(body: str) -> str | None:
    match = re.search(r"Editor channel=.*? sha1: ([0-9a-f]{40})", body)
    return match.group(1) if match else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--metadata-out", required=True)
    args = parser.parse_args()

    work_dir = Path(args.work_dir)
    downloads_dir = work_dir / "downloads"
    unpack_dir = work_dir / "defold"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    unpack_dir.mkdir(parents=True, exist_ok=True)

    releases = fetch_json(RELEASES_URL)
    if not isinstance(releases, list):
        raise RuntimeError("unexpected GitHub releases response")
    release = choose_release(releases)

    asset = None
    for candidate in release.get("assets", []):
        if isinstance(candidate, dict) and candidate.get("name") == ASSET_NAME:
            asset = candidate
            break
    if asset is None:
        raise RuntimeError(f"could not find {ASSET_NAME} asset")

    archive_path = downloads_dir / ASSET_NAME
    download(str(asset["browser_download_url"]), archive_path)
    with tarfile.open(archive_path, "r:gz") as archive:
        archive.extractall(unpack_dir)

    metadata = {
        "release_tag": release.get("tag_name"),
        "release_name": release.get("name"),
        "release_url": release.get("html_url"),
        "release_published_at": release.get("published_at"),
        "target_commitish": release.get("target_commitish"),
        "editor_commit_sha": editor_sha(str(release.get("body", ""))),
        "asset_name": asset.get("name"),
        "asset_url": asset.get("browser_download_url"),
        "asset_size_bytes": asset.get("size"),
        "asset_digest": asset.get("digest"),
        "archive_path": str(archive_path.resolve()),
        "unpack_dir": str(unpack_dir.resolve()),
    }
    metadata_out = Path(args.metadata_out)
    metadata_out.parent.mkdir(parents=True, exist_ok=True)
    metadata_out.write_text(json.dumps(metadata, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
