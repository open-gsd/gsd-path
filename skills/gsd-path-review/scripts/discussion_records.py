#!/usr/bin/env python3
"""Manage GSD Path discussion records as a recoverable paired transaction."""

import argparse
import fcntl
import json
import os
import shutil
import sys
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator, Optional, Sequence

import archive_milestone


class DiscussionError(RuntimeError):
    pass


APPEND_TRANSACTION = ".discussion-append-transaction.json"
FILES = ("DIALOGUE.md", "ANSWERS.md")
PHASES = {"onboard", "grill", "research", "synthesize", "plan", "build", "review"}


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.gsd-path-tmp"
    try:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()


def project_root(repo: Path) -> tuple[Path, Path, Path]:
    root = repo.resolve()
    project = root / ".project"
    state = project / "STATE.md"
    if project.is_symlink() or not project.is_dir():
        raise DiscussionError(f".project must be a real directory: {project}")
    if state.is_symlink() or not state.is_file():
        raise DiscussionError(f"STATE.md must be a real file: {state}")
    return root, project, state


@contextmanager
def state_lock(state: Path) -> Iterator[None]:
    with state.open("r", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def state_context(state: Path) -> tuple[str, str, str]:
    content = state.read_text(encoding="utf-8")
    if archive_milestone.frontmatter_value(content, "pipeline") != archive_milestone.PIPELINE_MARKER:
        raise DiscussionError("STATE.md is not owned by gsd-path/v1")
    phase = archive_milestone.frontmatter_value(content, "phase") or ""
    status = archive_milestone.frontmatter_value(content, "status") or ""
    configured_archive = archive_milestone.frontmatter_value(content, "archive") or "null"
    if phase not in PHASES or status not in {"active", "blocked", "done"}:
        raise DiscussionError(f"discussion is not available in state {phase}/{status}")
    return phase, status, configured_archive


def template_header(path: Path, record_prefix: str) -> str:
    if path.is_symlink() or not path.is_file() or not path.is_absolute():
        raise DiscussionError(f"template must be an absolute real file: {path}")
    content = path.read_text(encoding="utf-8")
    marker = f"\n{record_prefix}"
    if marker not in content:
        raise DiscussionError(f"template lacks sample record: {path}")
    return content.split(marker, 1)[0].rstrip() + "\n"


def record_count(directory: Path) -> int:
    lines = (directory / "DIALOGUE.md").read_text(encoding="utf-8").splitlines()
    return sum(
        archive_milestone.DIALOGUE_HEADING_PATTERN.fullmatch(line) is not None
        for line in lines
    )


def validate_or_empty(directory: Path) -> None:
    if directory.is_symlink() or not directory.is_dir():
        raise DiscussionError("discussion records must be a real directory")
    if sorted(path.name for path in directory.iterdir()) != sorted(FILES):
        raise DiscussionError("discussion directory must contain exactly DIALOGUE.md and ANSWERS.md")
    if record_count(directory) == 0:
        if "### D" in (directory / "DIALOGUE.md").read_text(encoding="utf-8"):
            raise DiscussionError("empty discussion has a malformed dialogue record")
        if "## Answer A" in (directory / "ANSWERS.md").read_text(encoding="utf-8"):
            raise DiscussionError("empty discussion has a malformed answer record")
        return
    try:
        archive_milestone.validate_discussion_directory(
            directory, require_dispositions=False
        )
    except archive_milestone.ArchiveError as error:
        raise DiscussionError(str(error)) from error


def finish_append(project: Path, discussion: Path) -> None:
    transaction = project / APPEND_TRANSACTION
    if not transaction.exists():
        return
    if transaction.is_symlink() or not transaction.is_file():
        raise DiscussionError("discussion append journal must be a real file")
    try:
        payload = json.loads(transaction.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DiscussionError(f"discussion append journal is unreadable: {error}") from error
    if payload.get("schema") != "gsd-path/discussion-append/v1":
        raise DiscussionError("discussion append journal has the wrong schema")
    files = payload.get("files")
    if (
        not isinstance(files, dict)
        or set(files) != set(FILES)
        or any(not isinstance(files[name], str) for name in FILES)
    ):
        raise DiscussionError("discussion append journal has invalid files")
    discussion.mkdir(exist_ok=True)
    for name in FILES:
        atomic_write(discussion / name, files[name])
    validate_or_empty(discussion)
    transaction.unlink()


def validate_contents(project: Path, files: dict) -> None:
    staging = project / ".discussion-validation-tmp"
    if staging.exists() or staging.is_symlink():
        if staging.is_symlink() or not staging.is_dir():
            raise DiscussionError(f"discussion validation path is invalid: {staging}")
        shutil.rmtree(staging)
    staging.mkdir()
    try:
        for name in FILES:
            (staging / name).write_text(files[name], encoding="utf-8")
        validate_or_empty(staging)
    finally:
        shutil.rmtree(staging)


def initialize_records(discussion: Path, dialogue_template: Path, answers_template: Path) -> None:
    if discussion.exists() or discussion.is_symlink():
        validate_or_empty(discussion)
        return
    staging = discussion.parent / ".discuss.gsd-path-tmp"
    if staging.exists() or staging.is_symlink():
        if staging.is_symlink() or not staging.is_dir():
            raise DiscussionError(f"discussion staging path is invalid: {staging}")
        shutil.rmtree(staging)
    staging.mkdir()
    try:
        (staging / "DIALOGUE.md").write_text(
            template_header(dialogue_template, "### D001"), encoding="utf-8"
        )
        (staging / "ANSWERS.md").write_text(
            template_header(answers_template, "## Answer A001"), encoding="utf-8"
        )
        os.replace(staging, discussion)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def prepare_locked(
    root: Path,
    project: Path,
    state: Path,
    dialogue_template: Path,
    answers_template: Path,
) -> tuple[Path, str, str]:
    phase, status, configured = state_context(state)
    discussion = project / "discuss"
    finish_append(project, discussion)
    if not archive_milestone.is_unset(configured):
        if (phase, status) != ("review", "active"):
            raise DiscussionError("archive recovery is allowed only in review/active")
        try:
            archive = archive_milestone.archive_from_state(root, configured)
        except archive_milestone.ArchiveError as error:
            raise DiscussionError(str(error)) from error
        if archive_milestone.archive_is_committed(root, configured):
            raise DiscussionError("committed discussion archives are immutable")
        archived = archive / "discuss"
        if not archived.is_dir():
            raise DiscussionError("uncommitted archive has no discussion records to resume")
        if not discussion.exists():
            staging = project / ".discuss.gsd-path-tmp"
            if staging.exists():
                shutil.rmtree(staging)
            shutil.copytree(archived, staging)
            os.replace(staging, discussion)
        else:
            try:
                archive_milestone.require_append_only_discussion(discussion, archived)
            except archive_milestone.ArchiveError as error:
                raise DiscussionError(str(error)) from error
    else:
        initialize_records(discussion, dialogue_template, answers_template)
    validate_or_empty(discussion)
    if state_context(state) != (phase, status, configured):
        raise DiscussionError("STATE.md changed while discussion records were prepared")
    return discussion, phase, status


def numbered_sections(lines: Sequence[str], pattern, boundaries) -> list[tuple]:
    return list(archive_milestone.record_sections(lines, pattern, boundaries))


def field(lines: Sequence[str], name: str) -> str:
    try:
        return archive_milestone.completed_bullet_field(lines, name, "ANSWERS.md")
    except archive_milestone.ArchiveError as error:
        raise DiscussionError(str(error)) from error


def pending_records(discussion: Path) -> list[dict]:
    if record_count(discussion) == 0:
        return []
    lines = (discussion / "ANSWERS.md").read_text(encoding="utf-8").splitlines()
    boundaries = (
        archive_milestone.ANSWER_HEADING_PATTERN,
        archive_milestone.DISPOSITION_HEADING_PATTERN,
    )
    answers = numbered_sections(lines, archive_milestone.ANSWER_HEADING_PATTERN, boundaries)
    dispositions = numbered_sections(
        lines, archive_milestone.DISPOSITION_HEADING_PATTERN, boundaries
    )
    resolved = {field(section, "Answer") for _, section in dispositions}
    pending = []
    for match, section in answers:
        identifier = f"A{int(match.group(1)):03d}"
        if (
            field(section, "Follow-up") == "required"
            and field(section, "Status") in {"final", "NEEDS-USER"}
            and identifier not in resolved
        ):
            pending.append(
                {
                    "answer": identifier,
                    "owner": field(section, "Next owner"),
                    "target": field(section, "Target artifact"),
                    "status": field(section, "Status"),
                }
            )
    return pending


def append_disposition(discussion: Path, project: Path, payload: dict) -> dict:
    answer = required_text(payload, "answer")
    pending = {record["answer"]: record for record in pending_records(discussion)}
    if answer not in pending:
        raise DiscussionError(f"answer is not pending disposition: {answer}")
    disposition_status = required_text(payload, "status")
    if disposition_status not in {
        "applied",
        "acknowledged-no-change",
        "superseded",
        "rejected-by-user",
    }:
        raise DiscussionError("disposition status is invalid")
    expected = pending[answer]
    owner = single_line(payload, "owner")
    artifact = single_line(payload, "artifact")
    expected_owner = (
        "user" if disposition_status == "rejected-by-user" else expected["owner"]
    )
    if owner != expected_owner:
        raise DiscussionError(f"disposition owner must be {expected_owner}")
    if artifact != expected["target"]:
        raise DiscussionError(f"disposition artifact must be {expected['target']}")
    lines = (discussion / "ANSWERS.md").read_text(encoding="utf-8").splitlines()
    boundaries = (
        archive_milestone.ANSWER_HEADING_PATTERN,
        archive_milestone.DISPOSITION_HEADING_PATTERN,
    )
    existing = numbered_sections(
        lines, archive_milestone.DISPOSITION_HEADING_PATTERN, boundaries
    )
    number = len(existing) + 1
    record_date = iso_date(payload)
    disposition = f"""\n## Disposition X{number:03d} — {record_date}

- **Answer**: {answer}
- **Status**: {disposition_status}
- **Owner**: {owner}
- **Artifact**: {artifact}
- **Evidence**: {single_line(payload, "evidence")}
"""
    files = {
        "DIALOGUE.md": (discussion / "DIALOGUE.md").read_text(encoding="utf-8"),
        "ANSWERS.md": (discussion / "ANSWERS.md").read_text(encoding="utf-8").rstrip()
        + "\n"
        + disposition,
    }
    validate_contents(project, files)
    atomic_write(
        project / APPEND_TRANSACTION,
        json.dumps(
            {"schema": "gsd-path/discussion-append/v1", "files": files},
            sort_keys=True,
        )
        + "\n",
    )
    finish_append(project, discussion)
    return {"answer": answer, "disposition": f"X{number:03d}"}


def required_text(payload: dict, name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise DiscussionError(f"append payload requires non-empty {name}")
    return value.strip()


def single_line(payload: dict, name: str) -> str:
    value = required_text(payload, name)
    if "\n" in value or "\r" in value:
        raise DiscussionError(f"append payload {name} must be one line")
    return value


def quote_block(value: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in value.splitlines())


def indent_block(value: str) -> str:
    return "\n".join(f"  {line}" if line else "  " for line in value.splitlines())


def iso_date(payload: dict) -> str:
    value = payload.get("date", date.today().isoformat())
    if not isinstance(value, str):
        raise DiscussionError("date must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise DiscussionError("date must be YYYY-MM-DD") from error
    if parsed.isoformat() != value:
        raise DiscussionError("date must be YYYY-MM-DD")
    return value


def append_record(discussion: Path, project: Path, phase: str, status: str, payload: dict) -> dict:
    count = record_count(discussion)
    number = count + 1
    dialogue_id = f"D{number:03d}"
    answer_id = f"A{number:03d}"
    dialogue_lines = (discussion / "DIALOGUE.md").read_text(encoding="utf-8").splitlines()
    if count:
        archive_milestone.validate_discussion_directory(
            discussion, require_dispositions=False
        )
    requested_thread = payload.get("thread", "new")
    existing_threads = {}
    if count:
        sections = numbered_sections(
            dialogue_lines,
            archive_milestone.DIALOGUE_HEADING_PATTERN,
            (archive_milestone.DIALOGUE_HEADING_PATTERN,),
        )
        for match, section in sections:
            existing_threads.setdefault(field(section, "Thread"), []).append(int(match.group(1)))
    if requested_thread == "new":
        thread_number = max((int(value[1:]) for value in existing_threads), default=0) + 1
        thread = f"T{thread_number:03d}"
        reply_to = supersedes = "none"
    elif requested_thread in existing_threads:
        thread = requested_thread
        prior = existing_threads[thread][-1]
        reply_to = f"D{prior:03d}"
        supersedes = f"A{prior:03d}"
    else:
        raise DiscussionError("thread must be new or an existing T### id")
    record_date = iso_date(payload)
    thread_status = single_line(payload, "thread_status")
    answer_status = single_line(payload, "status")
    if thread_status not in {"working", "NEEDS-USER", "final"}:
        raise DiscussionError("thread_status is invalid")
    if answer_status not in {"working", "NEEDS-USER", "final"}:
        raise DiscussionError("status is invalid")
    topic = single_line(payload, "topic")
    evidence = single_line(payload, "evidence")
    research = single_line(payload, "research")
    dialogue = f"""\n### {dialogue_id} — {record_date} — {phase}/{status} — {topic}

- **Thread**: {thread}
- **Reply to**: {reply_to}
- **User (verbatim)**:

{quote_block(required_text(payload, "user"))}

- **Assistant**:

{indent_block(required_text(payload, "assistant"))}

- **Evidence checked**: {evidence}
- **Research**: {research}
- **Thread status**: {thread_status}
"""
    answer = f"""\n## Answer {answer_id} — {record_date} — {topic}

- **Thread**: {thread}
- **Turn**: {dialogue_id}
- **Supersedes**: {supersedes}
- **Question**: {single_line(payload, "question")}
- **Status**: {answer_status}
- **Phase/status**: {phase}/{status}
- **Conclusion**: {single_line(payload, "conclusion")}
- **Reasoning / pushback**: {single_line(payload, "reasoning")}
- **Evidence**: {evidence}
- **Research**: {research}
- **Confidence**: {single_line(payload, "confidence")}
- **Unresolved**: {single_line(payload, "unresolved")}
- **Next owner**: {single_line(payload, "next_owner")}
- **Target artifact**: {single_line(payload, "target_artifact")}
- **Follow-up**: {single_line(payload, "follow_up")}
"""
    files = {
        "DIALOGUE.md": (discussion / "DIALOGUE.md").read_text(encoding="utf-8").rstrip() + "\n" + dialogue,
        "ANSWERS.md": (discussion / "ANSWERS.md").read_text(encoding="utf-8").rstrip() + "\n" + answer,
    }
    validate_contents(project, files)
    transaction = project / APPEND_TRANSACTION
    atomic_write(
        transaction,
        json.dumps(
            {"schema": "gsd-path/discussion-append/v1", "files": files},
            sort_keys=True,
        )
        + "\n",
    )
    finish_append(project, discussion)
    return {"answer": answer_id, "dialogue": dialogue_id, "thread": thread}


def load_payload(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise DiscussionError(f"append input must be a real file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DiscussionError(f"append input is unreadable: {error}") from error
    if not isinstance(payload, dict):
        raise DiscussionError("append input must contain one JSON object")
    return payload


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "command", choices=("prepare", "append", "pending", "dispose")
    )
    result.add_argument("--repo", type=Path, required=True)
    result.add_argument("--dialogue-template", type=Path)
    result.add_argument("--answers-template", type=Path)
    result.add_argument("--input", type=Path)
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        arguments = parser().parse_args(argv)
        root, project, state = project_root(arguments.repo)
        with state_lock(state):
            if arguments.command in {"pending", "dispose"}:
                discussion = project / "discuss"
                finish_append(project, discussion)
                if not discussion.exists():
                    if arguments.command == "dispose":
                        raise DiscussionError("discussion records do not exist")
                    result = {"pending": []}
                else:
                    validate_or_empty(discussion)
                    if arguments.command == "pending":
                        result = {"pending": pending_records(discussion)}
                    else:
                        if arguments.input is None:
                            raise DiscussionError("dispose requires --input")
                        result = append_disposition(
                            discussion, project, load_payload(arguments.input)
                        )
            else:
                if arguments.dialogue_template is None or arguments.answers_template is None:
                    raise DiscussionError("prepare and append require both bundled template paths")
                discussion, phase, status = prepare_locked(
                    root,
                    project,
                    state,
                    arguments.dialogue_template.resolve(),
                    arguments.answers_template.resolve(),
                )
                if arguments.command == "prepare":
                    result = {
                        "dialogue": str((discussion / "DIALOGUE.md").resolve()),
                        "answers": str((discussion / "ANSWERS.md").resolve()),
                        "phase_status": f"{phase}/{status}",
                        "records": record_count(discussion),
                    }
                else:
                    if arguments.input is None:
                        raise DiscussionError("append requires --input")
                    result = append_record(
                        discussion, project, phase, status, load_payload(arguments.input)
                    )
        print(json.dumps(result, sort_keys=True))
        return 0
    except (DiscussionError, archive_milestone.ArchiveError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
