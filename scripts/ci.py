#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
WORKFLOW_NAME = "Benchmark"
POLL_SECONDS = 3
POLL_TIMEOUT_SECONDS = 180


def run(*args: str, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(args),
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        command = " ".join(args)
        message = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise RuntimeError(f"{command}: {message}")
    return result


def make_snapshot_commit(head: str) -> tuple[str, tempfile.TemporaryDirectory[str] | None]:
    status = run("git", "status", "--porcelain=v1", "--untracked-files=all").stdout.strip()
    if not status:
        return head, None

    tempdir = tempfile.TemporaryDirectory(prefix="editor-metrics-ci-")
    env = os.environ.copy()
    env["GIT_INDEX_FILE"] = str(Path(tempdir.name) / "index")

    run("git", "read-tree", "HEAD", env=env)
    run("git", "add", "-A", "--", ".", env=env)
    tree = run("git", "write-tree", env=env).stdout.strip()
    head_tree = run("git", "rev-parse", "HEAD^{tree}").stdout.strip()
    if tree == head_tree:
        tempdir.cleanup()
        return head, None

    commit = run(
        "git",
        "commit-tree",
        tree,
        "-p",
        head,
        "-m",
        f"ci snapshot for {head}",
        env=env,
    ).stdout.strip()
    return commit, tempdir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow", default=WORKFLOW_NAME)
    parser.add_argument("--event", default="push", choices=["push", "workflow_dispatch"])
    parser.add_argument("--input", action="append", default=[])
    parser.add_argument("--keep-branch", action="store_true")
    parser.add_argument("--artifact-dir", default=str(DIST))
    return parser.parse_args()


def parse_workflow_inputs(values: list[str]) -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = []
    for value in values:
        name, separator, raw = value.partition("=")
        if not separator or not name:
            raise RuntimeError(f"workflow input must be NAME=VALUE, got {value!r}")
        parsed.append((name, raw))
    return parsed


def snapshot_branch_name(commit: str, event: str) -> str:
    prefix = "ci" if event == "push" else "dispatch"
    return f"{prefix}/{commit}"


def main() -> int:
    args = parse_args()
    tempdir: tempfile.TemporaryDirectory[str] | None = None
    branch = ""
    pushed = False

    def handle_signal(signum: int, _frame: object) -> None:
        raise KeyboardInterrupt(f"signal {signum}")

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        run("git", "rev-parse", "--show-toplevel")
        run("git", "remote", "get-url", "origin")
        run("gh", "auth", "status")
        workflow_inputs = parse_workflow_inputs(args.input)
        if workflow_inputs and args.event != "workflow_dispatch":
            raise RuntimeError("--input requires --event workflow_dispatch")
        repo = run("gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner").stdout.strip()
        head = run("git", "rev-parse", "HEAD").stdout.strip()
        commit, tempdir = make_snapshot_commit(head)
        branch = snapshot_branch_name(commit, args.event)

        if run(
            "git",
            "ls-remote",
            "--exit-code",
            "--heads",
            "origin",
            f"refs/heads/{branch}",
            check=False,
        ).returncode == 0:
            raise RuntimeError(f"remote branch already exists: {branch}")

        print(f"snapshot: {commit}", flush=True)
        print(f"branch: {branch}", flush=True)
        print("pushing snapshot...", flush=True)
        run("git", "push", "origin", f"{commit}:refs/heads/{branch}")
        pushed = True

        pushed_after = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if args.event == "workflow_dispatch":
            print("dispatching workflow...", flush=True)
            command = ["gh", "workflow", "run", args.workflow, "--ref", branch]
            for name, value in workflow_inputs:
                command.extend(["--raw-field", f"{name}={value}"])
            run(*command)

        print("waiting for workflow run...", flush=True)
        run_id: int | None = None
        deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
        while time.monotonic() < deadline and run_id is None:
            result = run(
                "gh",
                "run",
                "list",
                "--workflow",
                args.workflow,
                "--branch",
                branch,
                "--event",
                args.event,
                "--json",
                "databaseId,headSha,createdAt",
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                for item in json.loads(result.stdout):
                    if item.get("headSha") != commit:
                        continue
                    if item.get("createdAt", "") < pushed_after:
                        continue
                    database_id = item.get("databaseId")
                    if isinstance(database_id, int):
                        run_id = database_id
                        break
            if run_id is None:
                time.sleep(POLL_SECONDS)

        if run_id is None:
            raise RuntimeError(f"timed out waiting for {args.workflow} run on {branch}")

        url = run("gh", "api", f"repos/{repo}/actions/runs/{run_id}", "--jq", ".html_url").stdout.strip()
        print(f"run: {url}", flush=True)

        watch = subprocess.run(["gh", "run", "watch", str(run_id), "--exit-status"], cwd=ROOT, check=False)
        conclusion = run("gh", "api", f"repos/{repo}/actions/runs/{run_id}", "--jq", ".conclusion // .status").stdout.strip()
        print(f"result: {conclusion}", flush=True)

        artifact_dir = Path(args.artifact_dir)
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        print(f"downloading artifacts to {artifact_dir}...", flush=True)
        run("gh", "run", "download", str(run_id), "--dir", str(artifact_dir), check=False)
        return watch.returncode
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        if pushed and branch and not args.keep_branch:
            try:
                print(f"deleting remote branch {branch}...", flush=True)
                run("git", "push", "origin", "--delete", branch)
            except RuntimeError as exc:
                print(str(exc), file=sys.stderr)
                print(f"cleanup: git push origin --delete {branch}", file=sys.stderr)
        if tempdir is not None:
            tempdir.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
