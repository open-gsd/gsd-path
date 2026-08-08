---
name: gsd-path-synthesize
description: Deprecated compatibility alias for gsd-path-decide. Use only when the user explicitly invokes $gsd-path-synthesize; direct new work to $gsd-path-decide.
---

# Deprecated Alias: GSD Path Decide

This compatibility name remains until a separately approved breaking change.
Read the canonical
[GSD Path Decide skill](CANONICAL.md) fully and follow it
exactly. Treat the user's explicit `$gsd-path-synthesize` invocation as
explicit authorization for `$gsd-path-decide`, but use **decide** terminology
in every artifact and user-facing handoff.

An instruction to route to another phase is a caller handoff, not permission to trigger an explicit-only skill.
