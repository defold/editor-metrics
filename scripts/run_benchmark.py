#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROJECT = "defold/sample-pixel-line-platformer"
LAUNCH_TIMEOUT_SECONDS = 90
READY_WINDOW_SECONDS = 20


def run_command(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, check=False)


def find_editor_executable(unpack_dir: Path) -> Path:
    candidates = []
    for path in unpack_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.name != "Defold":
            continue
        if os.access(path, os.X_OK):
            candidates.append(path)
    if not candidates:
        raise RuntimeError("could not find Defold executable")
    candidates.sort(key=lambda path: len(path.parts))
    return candidates[0]


def project_archive_url(project: str) -> str:
    if project.count("/") != 1:
        raise RuntimeError(f"project must be in owner/name form, got {project!r}")
    owner, name = project.split("/", 1)
    return f"https://github.com/{owner}/{name}/archive/refs/heads/master.zip"


def project_archive_name(project: str) -> str:
    return project.replace("/", "-") + ".zip"


def download_project(projects_dir: Path, project: str) -> Path:
    archive_path = projects_dir / project_archive_name(project)
    request = urllib.request.Request(project_archive_url(project), headers={"User-Agent": "editor-metrics/phase-1"})
    with urllib.request.urlopen(request) as response, archive_path.open("wb") as output:
        shutil.copyfileobj(response, output)
    with zipfile.ZipFile(archive_path) as archive:
        top_level_names = {
            Path(name).parts[0]
            for name in archive.namelist()
            if name and not name.startswith("__MACOSX/")
        }
        archive.extractall(projects_dir)
    directories = [projects_dir / name for name in sorted(top_level_names) if (projects_dir / name).is_dir()]
    if len(directories) != 1:
        raise RuntimeError(f"expected one extracted project directory, got {sorted(top_level_names)}")
    return directories[0]


def make_executable(path: Path) -> None:
    current_mode = path.stat().st_mode
    path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=15)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--artifacts-dir", required=True)
    parser.add_argument("--metadata-out", required=True)
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    args = parser.parse_args()

    work_dir = Path(args.work_dir)
    artifacts_dir = Path(args.artifacts_dir)
    metadata_out = Path(args.metadata_out)
    logs_dir = artifacts_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    metadata: dict[str, object] = {
        "phase": "phase-1",
        "project": args.project,
        "launch_timeout_seconds": LAUNCH_TIMEOUT_SECONDS,
        "ready_window_seconds": READY_WINDOW_SECONDS,
        "status": "failed",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    try:
        fetch_result = run_command(
            [
                sys.executable,
                str(ROOT / "scripts" / "fetch_defold_build.py"),
                "--work-dir",
                str(work_dir),
                "--metadata-out",
                str(artifacts_dir / "defold-build.json"),
            ]
        )
        write_text(logs_dir / "fetch.stdout.log", fetch_result.stdout)
        write_text(logs_dir / "fetch.stderr.log", fetch_result.stderr)
        metadata["fetch_returncode"] = fetch_result.returncode
        if fetch_result.returncode != 0:
            raise RuntimeError("failed to fetch Defold build")

        build_metadata = json.loads((artifacts_dir / "defold-build.json").read_text())
        unpack_dir = Path(build_metadata["unpack_dir"])
        editor_executable = find_editor_executable(unpack_dir)
        make_executable(editor_executable)
        metadata["editor_executable"] = str(editor_executable.resolve())

        projects_dir = work_dir / "projects"
        projects_dir.mkdir(parents=True, exist_ok=True)
        project_dir = download_project(projects_dir, args.project)
        metadata["project_dir"] = str(project_dir.resolve())

        env = os.environ.copy()
        editor_log = logs_dir / "editor.stdout.log"
        editor_err = logs_dir / "editor.stderr.log"

        start = time.monotonic()
        with editor_log.open("w") as stdout_handle, editor_err.open("w") as stderr_handle:
            process = subprocess.Popen(
                [
                    "xvfb-run",
                    "-a",
                    str(editor_executable),
                    str(project_dir),
                ],
                cwd=project_dir,
                env=env,
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
            )
            launched = False
            exit_code = None
            try:
                deadline = time.monotonic() + LAUNCH_TIMEOUT_SECONDS
                while time.monotonic() < deadline:
                    exit_code = process.poll()
                    if exit_code is not None:
                        break
                    if time.monotonic() - start >= READY_WINDOW_SECONDS:
                        launched = True
                        break
                    time.sleep(1)
            finally:
                terminate_process(process)

        duration_ms = int((time.monotonic() - start) * 1000)
        metadata["editor_launch_duration_ms"] = duration_ms
        metadata["editor_launch_sustained"] = launched
        metadata["editor_exit_code_before_termination"] = exit_code
        if not launched:
            raise RuntimeError("editor did not stay alive long enough under xvfb")

        metadata["status"] = "ok"
        metadata_out.parent.mkdir(parents=True, exist_ok=True)
        metadata_out.write_text(json.dumps(metadata, indent=2) + "\n")
        return 0
    except Exception as exc:
        metadata["error"] = str(exc)
        metadata_out.parent.mkdir(parents=True, exist_ok=True)
        metadata_out.write_text(json.dumps(metadata, indent=2) + "\n")
        raise


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
