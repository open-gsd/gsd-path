#!/usr/bin/env python3
"""Own immutable project runtimes, explicit upgrades, restoration and migration."""
import hashlib
import base64
import json
import os
from pathlib import Path
import shutil
import shlex
import tempfile
from contextlib import contextmanager

try:
    from . import status_runtime
except ImportError:
    import status_runtime

RUNTIME_FILES = (
    "pipeline_state.py", "roadmap.py", "check_handoffs.py", "check_task_briefs.py",
    "isolation.py", "discussion_records.py", "pipeline_git.py", "promote_lookahead.py",
    "detect_project.py", "pipeline_diagnose.py", "pipeline_undo.py", "archive_milestone.py",
    "review_panel.py", "_common.py", "worktree_paths.py", "build_recovery.py",
    "state_checkpoint.py", "state_promote.py", "discussion_validate.py", "integration.py",
    "build_state.py", "lean_verification.py", "check_docs_audit.py",
    "path_config.py", "model_policy.py", "loop_run.py",
)
GUARDS = ("guard_hook.py", "git_guard.py")


def guard_launcher(name):
    if name not in GUARDS:
        raise ValueError("unknown runtime guard")
    return ("#!/usr/bin/env python3\n# gsd-path guard — stable runtime launcher\n"
            "import sys\nsys.dont_write_bytecode = True\nfrom pathlib import Path\n"
            "from status_runtime import run_guard\n"
            "try:\n"
            f"    run_guard(Path(__file__).resolve().parent.parent, {name!r})\n"
            "except (OSError, ValueError) as error:\n"
            "    print(str(error), file=sys.stderr)\n"
            f"    raise SystemExit({2 if name == 'guard_hook.py' else 1})\n")


def source_manifest(source):
    version = json.loads((source / "package.json").read_text())["version"]
    files = {}
    for name in (*RUNTIME_FILES, *GUARDS, "status_runtime.py"):
        path = source / "scripts" / name
        if path.is_symlink():
            raise ValueError(f"symlinked runtime source: {path}")
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {"version": version, "files": files}
    pin = {"schema": status_runtime.RUNTIME_SCHEMA, "version": version,
           "digest": status_runtime.manifest_digest(manifest)}
    return manifest, pin


def pin_text(pin):
    return json.dumps(pin, indent=2, sort_keys=True) + "\n"


@contextmanager
def publication_lock(parent, digest):
    """The OS releases this external lock even if publication is interrupted."""
    lock = parent / ("." + digest + ".lock")
    if lock.is_symlink():
        raise ValueError(f"unsafe runtime publication lock: {lock}")
    descriptor = os.open(lock, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        if os.name == "nt":
            import msvcrt
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def publish(source, *, expected=None, dry_run=False, repair=False):
    manifest, pin = source_manifest(source)
    if expected is not None and any(pin[key] != expected.get(key) for key in pin):
        raise ValueError(f"source does not match declared runtime {expected['version']} ({expected['digest']}); use its matching package")
    if dry_run:
        return pin
    parent = status_runtime.runtime_home()
    if any(p.is_symlink() for p in (parent, parent.parent)):
        raise ValueError(f"unsafe runtime storage: {parent}")
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / pin["digest"]
    if destination.is_symlink():
        raise ValueError(f"unsafe runtime storage: {destination}")
    if destination.exists():
        try:
            status_runtime.validate_runtime(pin)
            return pin
        except ValueError:
            if not repair:
                raise
    with tempfile.TemporaryDirectory(prefix=".runtime-stage-", dir=parent) as temporary:
        staging = Path(temporary) / "runtime"
        staging.mkdir()
        for name, digest in manifest["files"].items():
            shutil.copyfile(source / "scripts" / name, staging / name)
            if hashlib.sha256((staging / name).read_bytes()).hexdigest() != digest:
                raise ValueError(f"runtime source changed while installing: {name}")
        (staging / "manifest.json").write_text(pin_text(manifest), encoding="utf-8")
        # Serialize publication/repair, including two explicit restorations.
        previous = Path(temporary) / "previous"
        with publication_lock(parent, pin["digest"]):
            if destination.exists():
                try:
                    status_runtime.validate_runtime(pin)
                    return pin
                except ValueError:
                    if not repair:
                        raise
                    destination.rename(previous)
            try:
                staging.rename(destination)
                status_runtime.validate_runtime(pin)
            except BaseException:
                if previous.exists() and not destination.exists():
                    previous.rename(destination)
                raise
    return pin


def prepare(source, project, *, dry_run=False):
    declaration = project / ".gsd-path/runtime.json"
    if os.path.lexists(declaration):
        pin = status_runtime.declaration(project)
        status_runtime.validate_runtime(pin)
        return pin
    if os.path.lexists(project / ".gsd-path/runtime"):
        raise ValueError("legacy project runtime requires explicit migration before updating; run: "
                         f"npx @opengsd/gsd-path@latest --runtime-migrate --project {shlex.quote(str(project.resolve()))}; "
                         "then retry the update. Migration produces a reviewable Git diff")
    return publish(source, dry_run=dry_run)


def atomic_config(path, content):
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError(f"unsafe project runtime configuration: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.gsd-path-tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content.encode("utf-8"))
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def migration_journal(project):
    identity = hashlib.sha256(os.fsencode(project.resolve())).hexdigest()
    return Path.home() / ".gsd-path" / "runtime-migrations" / (identity + ".json")


def recover_migration(project):
    journal = migration_journal(project)
    if not os.path.lexists(journal):
        return
    if journal.is_symlink():
        raise ValueError(f"unsafe runtime migration journal: {journal}")
    data = json.loads(journal.read_text())
    recorded_project = data.get("project")
    if (data.get("schema") != "gsd-path/runtime-migration/v1"
            or not isinstance(recorded_project, str)
            or Path(recorded_project).resolve() != project.resolve()):
        raise ValueError(f"invalid runtime migration journal: {journal}")
    allowed = {".gsd-path/runtime.json", ".gsd-path/status_runtime.py"}
    allowed.update(".gsd-path/" + n for n in GUARDS)
    allowed.update(".gsd-path/runtime/" + n for n in RUNTIME_FILES)
    entries = data.get("files")
    if not isinstance(entries, dict) or not set(entries) <= allowed:
        raise ValueError(f"invalid runtime migration paths: {journal}")
    # Refuse to overwrite edits made after interruption.
    for relative, change in entries.items():
        path = project / relative
        if path.is_symlink() or path.parent.is_symlink():
            raise ValueError(f"unsafe migration recovery path: {path}")
        current = base64.b64encode(path.read_bytes()).decode() if path.exists() else None
        if current not in (change["before"], change["after"]):
            raise ValueError(f"migration recovery would overwrite a changed file: {path}")
    for relative, change in entries.items():
        path = project / relative
        if change["before"] is None:
            path.unlink(missing_ok=True)
        else:
            atomic_config(path, base64.b64decode(change["before"]).decode("utf-8"))
    journal.unlink()


def operate(source, project, action, *, dry_run=False):
    if project.is_symlink() or (project / ".gsd-path").is_symlink():
        raise ValueError("unsafe project runtime directory")
    if action == "restore":
        pin = status_runtime.declaration(project)
        publish(source, expected=pin, dry_run=dry_run, repair=True)
        return pin
    if action == "upgrade":
        status_runtime.declaration(project)
        pin = publish(source, dry_run=dry_run)
        if not dry_run:
            launcher = project / ".gsd-path/status_runtime.py"
            original = launcher.read_text(encoding="utf-8")
            replacement = (source / "scripts/status_runtime.py").read_text(encoding="utf-8")
            # Both launchers understand the same declaration schema. Publishing
            # the compatible launcher first leaves the old selection usable.
            if replacement != original:
                atomic_config(launcher, replacement)
            try:
                atomic_config(project / ".gsd-path/runtime.json", pin_text(pin))
            except BaseException:
                if replacement != original:
                    atomic_config(launcher, original)
                raise
        return pin
    if action != "migrate":
        raise ValueError("unknown runtime operation")
    # Migration changes only reviewed managed files and never stages or commits.
    import subprocess
    if not dry_run:
        recover_migration(project)
    runtime = project / ".gsd-path/runtime"
    if runtime.is_symlink() or not runtime.is_dir():
        raise ValueError("migration requires a real legacy runtime directory")
    entries = list(runtime.iterdir())
    if {p.name for p in entries} - set(RUNTIME_FILES):
        raise ValueError("legacy runtime contains unknown files; preserve and resolve them before migration")
    managed = entries + [project / ".gsd-path/status_runtime.py"]
    managed += [project / ".gsd-path" / n for n in GUARDS if (project / ".gsd-path" / n).exists()]
    for path in managed:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"unsafe migration file: {path}")
        marker = ("gsd-path project runtime" if path.parent == runtime else
                  "gsd-path project status launcher" if path.name == "status_runtime.py" else "gsd-path guard")
        if marker not in path.read_text(encoding="utf-8"):
            raise ValueError(f"unmanaged migration file: {path}")
        relative = path.relative_to(project).as_posix()
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", "--", relative], cwd=project, capture_output=True)
        if tracked.returncode == 0:
            clean = subprocess.run(["git", "status", "--porcelain", "--", relative], cwd=project, capture_output=True, check=True)
            if clean.stdout:
                raise ValueError(f"locally modified migration file: {path}")
        elif path.read_bytes() != (source / "scripts" / path.name).read_bytes():
            raise ValueError(f"untracked migration file differs from source: {path}")
    pin = publish(source, dry_run=dry_run)
    if dry_run:
        return pin
    originals = {p: p.read_bytes() for p in managed}
    declaration = project / ".gsd-path/runtime.json"
    if os.path.lexists(declaration):
        raise ValueError("runtime declaration already exists; refusing legacy migration")
    updates = {project / ".gsd-path/status_runtime.py": (source / "scripts/status_runtime.py").read_bytes(),
               declaration: pin_text(pin).encode()}
    updates.update({p: None for p in entries})
    updates.update({p: guard_launcher(p.name).encode() for p in managed if p.name in GUARDS})
    changes = {p.relative_to(project).as_posix(): {
        "before": base64.b64encode(originals[p]).decode() if p in originals else None,
        "after": base64.b64encode(content).decode() if content is not None else None,
    } for p, content in updates.items()}
    journal = migration_journal(project)
    atomic_config(journal, pin_text({"schema": "gsd-path/runtime-migration/v1", "project": str(project.resolve()), "files": changes}))
    try:
        for path, content in updates.items():
            if content is None:
                path.unlink()
            else:
                atomic_config(path, content.decode("utf-8"))
        runtime.rmdir()
    except BaseException:
        recover_migration(project)
        raise
    journal.unlink()
    return pin
