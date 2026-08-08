---
name: gsd-path-review
description: Deprecated compatibility alias for gsd-path-ship. Use only when the user explicitly invokes $gsd-path-review; direct new work to $gsd-path-ship.
---

# Deprecated Alias: GSD Path Ship

This compatibility name remains until a separately approved breaking change.
Read the canonical
[GSD Path Ship skill](CANONICAL.md) fully and follow it exactly.
Treat the user's explicit `$gsd-path-review` invocation as explicit
authorization for `$gsd-path-ship`; verification still runs before the final
shipping approval, and no archive or ship mutation occurs before that gate.

An instruction to route to another phase is a caller handoff, not permission to trigger an explicit-only skill.
