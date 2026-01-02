# Silo Documentation - How to Use with Claude Projects

## Quick Start

1. **Create a Claude Project** for the silo you're working on
2. **Add these files** to the project:
   - The appropriate `SILO_*.md` file
   - The actual `.py` files from that silo
3. **Start the conversation** - Claude will understand the full context

## The 6 Silos

| Claude Project Name | Include This Doc | Include These Source Files |
|---------------------|------------------|---------------------------|
| `continuum-core` | `SILO_CORE.md` | `src/core/*`, `src/comfy_client/*`, `workflows/*` |
| `continuum-director` | `SILO_DIRECTOR.md` | `src/director/*`, `src/memory/*` |
| `continuum-studio` | `SILO_STUDIO.md` | `src/studio/*`, `src/renderers/*` |
| `continuum-audit` | `SILO_AUDIT.md` | `src/audit/*` |
| `continuum-sonic` | `SILO_SONIC.md` | `src/sonic/*` |
| `continuum-post` | `SILO_POST.md` | `src/post/*` |

## What Each SILO.md Contains

Each document gives Claude:

1. **Bird's eye architecture** - Where this silo fits in the system
2. **Interfaces EXPOSED** - Types/classes other silos depend on
3. **Interfaces CONSUMED** - What this silo needs from others  
4. **Key files** - What each file does
5. **Common tasks** - Patterns for typical work
6. **Current state** - What's working, what's stubbed

## Cross-Silo Work

When you need to work across silos:

```
Include in Claude Project:
├── SILO_STUDIO.md      ← Primary silo
├── SILO_AUDIT.md       ← Secondary silo (for context)
├── src/studio/*        ← Primary source files
└── src/audit/*         ← Secondary source files (optional)
```

Then tell Claude: "This task spans Studio and Audit silos."

## Optional: Include main.py

`main.py` is the orchestrator that wires all silos together. Include it when:
- Integrating multiple silos
- Understanding how silos connect
- Debugging end-to-end issues

## File Sizes

| Silo | SILO.md | Source Files | Total Est. |
|------|---------|--------------|------------|
| Core | ~8 KB | ~100 KB | ~108 KB |
| Director | ~8 KB | ~90 KB | ~98 KB |
| Studio | ~10 KB | ~150 KB | ~160 KB |
| Audit | ~6 KB | ~60 KB | ~66 KB |
| Sonic | ~8 KB | ~100 KB | ~108 KB |
| Post | ~6 KB | ~60 KB | ~66 KB |

All silos fit comfortably within Claude Projects limits.

## Keeping Docs Updated

When you make significant changes to a silo:

1. Update the "Current State / Known Issues" section
2. Update "Interfaces Exposed" if you add/change public APIs
3. Commit the SILO.md alongside your code changes