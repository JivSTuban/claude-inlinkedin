# Design: /dev Skill — Context-First Development Session
Date: 2026-06-16

## Summary

A single `/dev [source]` skill that replaces GSD with a workflow native to our Obsidian + graphify toolchain. Front-loads all context before touching code, confirms the plan once, then executes autonomously to completion.

## Architecture: Option B — Context-First with Adaptive Execution

```
/dev [source]
  1. GATHER   → detect source, extract requirements
  2. CONTEXT  → graphify query + Obsidian (NOW, DECISIONS, WORKS, FAILURES)
  3. PLAN     → synthesize → write PLAN.md → present to user
  4. CONFIRM  ← single checkpoint (user approves or edits)
  5. EXECUTE  → work tasks top-to-bottom, update TASKS.md live
  6. VERIFY   → check WORKS patterns + FAILURES traps + run tests
  7. LOG      → append JOURNAL, update NOW, promote learnings
```

Re-entry flags: `--plan`, `--exec`, `--verify`

## Source Detection

| Source | Detection | Tool |
|--------|-----------|------|
| `app.slack.com` URL or `#channel` | Slack URL/mention | Slack MCP → Playwright fallback |
| `fathom.video` / `loom.com` | Meeting recording | ctx_fetch_and_index |
| `notion.so` | Notion page | Notion MCP |
| `github.com/*/issues/*` or `/pull/*` | GitHub issue/PR | gh CLI |
| Any other URL | Generic page | ctx_fetch_and_index |
| No source / plain text | Inline requirement | Read from message |

### Playwright Fallback (Slack + others)
- Profile at `~/.claude/browser-profiles/<service>/`
- If profile exists: open silently, extract content
- If missing: STOP → tell user to run `/dev-auth <service>`

## Credential + Service Manifest

`~/.claude/services.json` — maps services to connection methods.

Connection priority per service:
1. MCP (check if `mcp_prefix` tools are loaded via ToolSearch)
2. Browser profile (`~/.claude/browser-profiles/<service>/` — must contain files)
3. Keychain API token (`security find-generic-password -s <service> -a <account> -w`)

## /refresh Integration

After loading memory files, /refresh also:
1. Reads `~/.claude/services.json`
2. Checks each service's connection status
3. Reports: `Services: Slack [MCP ✓], Notion [MCP ✓], Fathom [no profile]`

## Plan Format (PLAN.md)

Written to `~/Second Brain/Projects/<Project>/PLAN.md`:

```markdown
# Plan: <Goal>
Date: YYYY-MM-DD

## Goal
## Context Summary
## Risks  ← from FAILURES.md matches
## Tasks  ← [ ] numbered, file:line estimates
## Success Criteria
```

## Obsidian KB Structure Per Project

```
~/Second Brain/Projects/<ProjectName>/
  NOW.md        current state, active work, blockers
  DECISIONS.md  architectural decisions
  TASKS.md      open/done task list (updated live during execute)
  WORKS.md      patterns and runbooks
  FAILURES.md   traps and root causes
  PLAN.md       current plan (written by /dev)
  JOURNAL.md    append-only session log
```

## Execute Phase

- Per task: mark `[→]` in-progress → do work → mark `[x]` done → atomic commit
- Update TASKS.md via `obsidian_patch_note` after each task
- If blocked: note in TASKS.md, continue unblocked tasks, report at end

## Verify Phase

1. Re-read WORKS.md relevant sections — does implementation match patterns?
2. Scan FAILURES.md — any traps that apply?
3. Run tests if present
4. Check all success criteria from PLAN.md

## Log Phase

- JOURNAL.md: append goal + done + impact + commit count
- NOW.md: remove completed work, note new blockers
- WORKS.md: append new patterns discovered
- FAILURES.md: append new traps hit (with root cause)

## Setup Skill: /dev-auth

Mini-skill for first-time service setup:
1. Opens Playwright with empty profile at `~/.claude/browser-profiles/<service>/`
2. Navigates to service login page
3. User logs in manually
4. Profile is saved for all future headless sessions
5. Updates `~/.claude/services.json`

## Files to Build

| File | Purpose |
|------|---------|
| `~/.claude/skills/dev/SKILL.md` | Main /dev skill |
| `~/.claude/skills/dev-auth/SKILL.md` | Browser profile setup |
| `~/.claude/services.json` | Service connection manifest |
| `~/.claude/skills/refresh/SKILL.md` | Updated to include services check |
