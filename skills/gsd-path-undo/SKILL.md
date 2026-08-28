---
name: gsd-path-undo
description: Use only when the user explicitly invokes $gsd-path-undo. Preview and apply helper-owned undo of an unpublished checkpoint, last task landing, uncommitted ship archive, or untracked lookahead track. Never invent git reset, revert, or force-push.
---

# GSD Path Undo

One invocation = one preview, then apply only after explicit user confirmation.
The bundled [pipeline_undo.py](scripts/pipeline_undo.py) is the only undo
authority; do not reimplement git reset in model reasoning.

This skill never advances a phase gate, never force-pushes, and never rewrites
a commit that is an ancestor of `origin/main`.

## Process

1. **Preview.** Run `python3 <absolute-bundled-pipeline_undo.py> preview --repo
   <absolute-root>`. Treat the JSON as the only classification. On helper
   error, present **Outcome** with the error, **Review** linking STATE.md when
   it exists, and **Next** naming `$gsd-path-forensics` when the pipeline looks
   stuck.
2. **Blocked.** When `target.kind` is `null`, report every `target.blocked`
   reason. **Next** is the retry named in those reasons, or `$gsd-path-forensics`.
   Stop. Do not apply.
3. **Confirm.** Present **Outcome** as the `target.effects` list, **Review**
   linking STATE.md, and **Next** asking whether to apply that exact kind
   (recommended only when `apply` is non-null) or stop. Do not apply until the
   user confirms.
4. **Apply.** After confirmation, run `python3 <absolute-bundled-pipeline_undo.py>
   apply --repo <absolute-root> --kind <target.kind> --expected-head
   <target.head>` using the preview values verbatim. A mismatch means HEAD
   moved: rerun preview, do not invent a SHA.
5. **Report.** **Outcome** is `status: applied` plus the new STATE phase/status.
   **Review** links STATE.md. **Next** names `$gsd-path status` to inspect
   without advancing.

## Rules

- Never run `git reset`, `git revert`, `git push --force`, or `git checkout`
  except through this helper.
- Never undo a ship commit, integration merge, abandon commit, or promotion
  commit. Those are blocked findings, not apply targets.
- A published HEAD (`origin/<STATE.branch>` equals HEAD) is blocked.
- Pending helper journals are blocked: resume that transaction instead.
