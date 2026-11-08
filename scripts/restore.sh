#!/usr/bin/env bash
# Puts Hive back from a backup (Settings → Backup), on this machine or a new one. Stop Hive first.
#   bash scripts/restore.sh s3://my-bucket/hive                  the newest backup there
#   bash scripts/restore.sh s3://my-bucket/hive/hive-backup-20261108-030000.tar.gz
#   bash scripts/restore.sh /backups/hive                        the newest backup in a folder (or a file)
# What it does:
#   - data/ comes back (the one already here is moved to data.before-restore-<time>, nothing is deleted);
#   - each project folder is cloned from GitHub if it's missing, and the branches only this machine had come back
#     from the backup (a branch that's newer here is left alone; a different one is kept as refs/hive/restored/…);
#   - the worktrees come back;
#   - Claude Code's conversations come back, and its sign-in if this machine has none;
#   - the agents and the task hook are installed again (scripts/install.sh).
set -euo pipefail
KIT="$(cd "$(dirname "$0")/.." && pwd)"

if [ $# -ne 1 ]; then
  sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
fi
if [ -f "$KIT/data/hive.pid" ] && kill -0 "$(cat "$KIT/data/hive.pid")" 2>/dev/null; then
  echo "Hive is running. Stop it first: bash scripts/stop.sh"
  exit 1
fi

python3 - "$KIT" "$1" <<'PY'
import datetime as dt, json, os, re, shutil, subprocess, sys, tarfile, tempfile
from pathlib import Path

kit, source = Path(sys.argv[1]), sys.argv[2].rstrip("/")
NAME = re.compile(r"^hive-backup-\d{8}-\d{6}\.tar\.gz$")
home = Path.home()
notes = []


def run(*cmd, cwd=None, check=True):
    done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and done.returncode != 0:
        sys.exit(f"{' '.join(cmd)} failed: {(done.stderr or done.stdout).strip()}")
    return done


def git(folder, *args, check=False):
    return run("git", "-C", str(folder), *args, check=check)


tmp = Path(tempfile.mkdtemp(prefix="hive-restore-"))
try:
    # 1. the archive
    if source.startswith("s3://"):
        if not shutil.which("aws"):
            sys.exit("The AWS CLI (aws) is needed to read from S3.")
        if not NAME.match(source.rsplit("/", 1)[-1]):
            names = sorted(l.split()[-1] for l in run("aws", "s3", "ls", source + "/").stdout.splitlines()
                           if l.split() and NAME.match(l.split()[-1]))
            if not names:
                sys.exit(f"No Hive backup in {source}.")
            source = f"{source}/{names[-1]}"
        archive = tmp / source.rsplit("/", 1)[-1]
        print(f"Downloading {source}…")
        run("aws", "s3", "cp", "--only-show-errors", source, str(archive))
    else:
        path = Path(source).expanduser()
        if path.is_dir():
            names = sorted(p.name for p in path.glob("hive-backup-*.tar.gz") if NAME.match(p.name))
            if not names:
                sys.exit(f"No Hive backup in {path}.")
            path = path / names[-1]
        if not path.is_file():
            sys.exit(f"No such backup: {path}")
        archive = path
    print(f"Restoring {archive.name}")
    unpacked = tmp / "x"
    with tarfile.open(archive) as tar:
        if hasattr(tarfile, "data_filter"):
            tar.extractall(unpacked, filter="data")
        else:
            for m in tar.getmembers():
                if m.name.startswith(("/", "..")) or "/../" in m.name:
                    sys.exit(f"Refusing a backup with an unsafe path: {m.name}")
            tar.extractall(unpacked)
    manifest = json.loads((unpacked / "manifest.json").read_text())

    # 2. data/
    data = kit / "data"
    if data.exists() and any(data.iterdir()):
        aside = kit / f"data.before-restore-{dt.datetime.now():%Y%m%d-%H%M%S}"
        data.rename(aside)
        notes.append(f"The data that was here is in {aside}.")
    shutil.copytree(unpacked / "data", data)
    print(f"✓ data/ (from {manifest['made']})")

    # 3. projects, branches, worktrees
    for p in manifest["projects"]:
        project = Path(p["path"])
        if not (project / ".git").exists():
            if not p.get("origin"):
                notes.append(f"{project} is missing and has no GitHub address: restore it yourself.")
                continue
            project.parent.mkdir(parents=True, exist_ok=True)
            print(f"Cloning {p['origin']} into {project}…")
            run("git", "clone", "--quiet", p["origin"], str(project))
            if p.get("branch"):
                git(project, "checkout", "--quiet", p["branch"])
        git(project, "fetch", "--quiet", "origin")
        if p.get("bundle"):
            bundle = unpacked / p["bundle"]
            checked_out = {l[len("branch "):] for l in git(project, "worktree", "list", "--porcelain").stdout.splitlines()
                           if l.startswith("branch ")}
            for line in git(project, "bundle", "list-heads", str(bundle)).stdout.splitlines():
                sha, ref = line.split(" ", 1)
                have = git(project, "rev-parse", "--verify", "--quiet", ref).stdout.strip()
                if have == sha:
                    continue
                target = ref
                if have:
                    if git(project, "merge-base", "--is-ancestor", sha, have).returncode == 0:
                        continue   # this machine's is newer
                    if git(project, "merge-base", "--is-ancestor", have, sha).returncode != 0 or ref in checked_out:
                        target = "refs/hive/restored/" + ref.split("/", 2)[-1]
                        notes.append(f"{project}: {ref} differs from the backup's; the backup's is in {target}.")
                elif ref in checked_out:
                    continue
                got = git(project, "fetch", "--quiet", str(bundle), f"+{ref}:{target}")
                if got.returncode != 0:
                    notes.append(f"{project}: couldn't restore {ref}: {got.stderr.strip()}")
            print(f"✓ {project}: branches")
        git(project, "worktree", "prune")
        for w in p.get("worktrees", []):
            if not Path(w["path"]).exists() and git(project, "rev-parse", "--verify", "--quiet", w["branch"]).returncode == 0:
                added = git(project, "worktree", "add", w["path"], w["branch"])
                if added.returncode != 0:
                    notes.append(f"Worktree {w['path']}: {added.stderr.strip()}")
        if p.get("worktrees"):
            print(f"✓ {project}: worktrees")

    # 4. Claude Code: conversations (never replacing a file), the sign-in only where there's none
    claude = unpacked / "claude"
    if claude.exists():
        for f in claude.rglob("*"):
            if f.is_file():
                to = home / f.relative_to(claude)
                if not to.exists():
                    to.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, to)
        if (claude / ".claude" / ".credentials.json").exists() and (home / ".claude" / ".credentials.json").exists():
            notes.append("This machine was already signed in to Claude Code, so its sign-in was kept.")
        print("✓ Claude Code conversations and sign-in")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

if manifest["kit"] != str(kit):
    notes.append(f"The backup came from Hive at {manifest['kit']}; it's now at {kit}.")
print()
for n in notes:
    print("• " + n)
PY

bash "$KIT/scripts/install.sh"
echo
echo "Restored. Start Hive the way you did before (with the same environment: CONSOLE_PASSWORD, CONSOLE_HOSTS, …):"
echo "  bash scripts/start.sh --background"
