# Continuum - Claude Code Guidelines

## Project Context
Read `docs/architecture_for_claude_code.md` for project overview. Read the latest handoff in `docs/Handoffs/` for current status.

## Source of Truth
- **Architecture**: `docs/ARCHITECTURE.md` — all changes must align with this
- **Lessons Learned**: `docs/LESSONS_LEARNED.md` — hard-won knowledge, don't repeat mistakes

---

## Rules for Making FIXES

1. **No rough patches** — Choose fixes that enhance the system overall, not just for the immediate test case. Solutions must be scalable to all future use cases.

2. **Explain the structure** — After code changes, explain why you structured it this way and how it prevents technical debt.

3. **Align with architecture** — Verify the fix aligns with `docs/ARCHITECTURE.md` and respects dependencies and the file's position in the architecture.

---

## Rules for Making UPDATES

1. **One file at a time** — Generate or update only one file at a time as per the plan.

2. **Explain the structure** — After code changes, explain why you structured it this way and how it prevents technical debt.

3. **Align with architecture** — Verify the update aligns with `docs/ARCHITECTURE.md` (concise version - architecture_for_claude_code.md) and respects dependencies and the file's position in the architecture.

4. **Lessons Learned is selective** — Only update `docs/LESSONS_LEARNED.md` (concise version - LESSONS_LEARNED_for_claude_code.md)when you expect Claude to make the same mistake in future. Keep it concise and relevant. This is NOT a roadmap or feature changelog.

---

## Key Architecture Principles

- **I2V-First**: Never use T2V for production. Shot 1 uses Hero Frame, Shot 2+ uses Bridge Frame.
- **Bridge Frame is mandatory**: Every shot change needs identity re-anchoring. Never bypass.
- **Redundant Identity Stack**: LoRA + IP-Adapter + ControlNet layers for defense in depth.
- **Two-Pass Rendering**: Pass 1 = Structure, Pass 2 = Refinement + Lip-sync + RIFE.
