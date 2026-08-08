---
name: gsd-path-onboard
description: Deprecated compatibility alias for gsd-path-inspect. Use only when the user explicitly invokes $gsd-path-onboard; direct new work to $gsd-path-inspect.
---

# Deprecated Alias: GSD Path Inspect

This compatibility name remains until a separately approved breaking change.
Read the canonical
[GSD Path Inspect skill](CANONICAL.md) fully and follow it
exactly. Treat the user's explicit `$gsd-path-onboard` invocation as explicit
authorization for `$gsd-path-inspect`, but use **inspect** terminology in every
artifact and user-facing handoff.

An instruction to route to another phase is a caller handoff, not permission to trigger an explicit-only skill.
