# Graph Report - jobi  (2026-06-16)

## Corpus Check
- 15 files · ~13,315 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 78 nodes · 103 edges · 11 communities (7 shown, 4 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 8 edges (avg confidence: 0.86)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `26457c88`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]

## God Nodes (most connected - your core abstractions)
1. `Design: /dev Skill — Context-First Development Session` - 13 edges
2. `AutonomousApply — Multi-Platform Expansion` - 13 edges
3. `Project Research Summary` - 10 edges
4. `Remote Job Platforms Research` - 6 edges
5. `runner.js (Platform Orchestrator)` - 6 edges
6. `linkedin-grow-runner.sh` - 5 edges
7. `AutonomousApply Project (claude-inlinkedin)` - 5 edges
8. `OpenAI (Job Matching / Cover Letters)` - 5 edges
9. `Platform Adapter Interface` - 5 edges
10. `pipeline.js (Shared Pre-filter + Apply Pipeline)` - 5 edges

## Surprising Connections (you probably didn't know these)
- `rebrowser-playwright (Anti-Detection)` --conceptually_related_to--> `Playwright MCP`  [INFERRED]
  .planning/research/STACK.md → AUTOMATION.md
- `AutonomousApply Project (claude-inlinkedin)` --references--> `linkedin-grow-runner.sh`  [EXTRACTED]
  README.md → AUTOMATION.md
- `AutonomousApply Project (claude-inlinkedin)` --references--> `linkedin-ensure-login.js`  [EXTRACTED]
  README.md → AUTOMATION.md
- `AutonomousApply Project (claude-inlinkedin)` --references--> `/linkedin-grow Claude Code Skill`  [EXTRACTED]
  README.md → AUTOMATION.md
- `Playwright Memory Leak (PM2 Production)` --references--> `PM2 Process Manager`  [EXTRACTED]
  .planning/research/PITFALLS.md → AUTOMATION.md

## Import Cycles
- None detected.

## Communities (11 total, 4 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.24
Nodes (13): Freemium Conversion Patterns, Anti-Bot Detection & Evasion, Freemium Abuse Prevention, Arc.dev Manual Pipeline Tracker, AutonomousApply — Multi-Platform Expansion, Freemium Model, OnlineJobs.ph Automation, Arc.dev Platform (+5 more)

### Community 1 - "Community 1"
Cohesion: 0.27
Nodes (11): Claude Code CLI, linkedin-ensure-login.js, ~/.linkedin_grow_last_run Timestamp File, linkedin-grow-runner.sh, /linkedin-grow Claude Code Skill, Persistent Chrome Profile, Playwright MCP, PM2 Process Manager (+3 more)

### Community 2 - "Community 2"
Cohesion: 0.25
Nodes (9): application_logs Table (Supabase), pipeline.js (Shared Pre-filter + Apply Pipeline), platform_stats Table (Supabase), Quota Enforcement Pattern, Stage 1 Cheap Filters (Salary/Keyword), user_plans Table (Supabase), user_subscriptions Table (Supabase), Dashboard Metrics That Matter (+1 more)

### Community 3 - "Community 3"
Cohesion: 0.25
Nodes (11): OnlineJobs Adapter (scraper.js), Platform Adapter Interface, RemoteOK Adapter (scraper.js), runner.js (Platform Orchestrator), scheduler.js (PM2 + node-cron), Wellfound Adapter (scraper.js), WeWorkRemotely Adapter (scraper.js), node-cron (Single PM2 Process Scheduler) (+3 more)

### Community 4 - "Community 4"
Cohesion: 0.38
Nodes (7): Credential Storage Security, Stripe + Supabase Billing Gotchas, job-automation-frontend (React/TypeScript/Vite), Supabase (Auth/DB/Realtime), rebrowser-playwright (Anti-Detection), Stripe Checkout + Billing Portal, Project Research Summary

### Community 5 - "Community 5"
Cohesion: 0.40
Nodes (6): Stage 2 AI Filters (Country/Timezone), Cover Letter Quality Signals, Country Restriction Detector, OpenAI (Job Matching / Cover Letters), Country Restriction Classifier (GPT-4o-mini), GPT-4o-mini with Structured Outputs

### Community 10 - "Community 10"
Cohesion: 0.13
Nodes (14): Architecture: Option B — Context-First with Adaptive Execution, Credential + Service Manifest, Design: /dev Skill — Context-First Development Session, Execute Phase, Files to Build, Log Phase, Obsidian KB Structure Per Project, Plan Format (PLAN.md) (+6 more)

## Knowledge Gaps
- **25 isolated node(s):** `Summary`, `Architecture: Option B — Context-First with Adaptive Execution`, `Playwright Fallback (Slack + others)`, `Credential + Service Manifest`, `/refresh Integration` (+20 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **4 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Project Research Summary` connect `Community 4` to `Community 1`, `Community 2`, `Community 3`, `Community 5`?**
  _High betweenness centrality (0.229) - this node is a cross-community bridge._
- **Why does `AutonomousApply — Multi-Platform Expansion` connect `Community 0` to `Community 1`, `Community 4`, `Community 5`?**
  _High betweenness centrality (0.177) - this node is a cross-community bridge._
- **Why does `pipeline.js (Shared Pre-filter + Apply Pipeline)` connect `Community 2` to `Community 4`, `Community 5`?**
  _High betweenness centrality (0.108) - this node is a cross-community bridge._
- **What connects `Summary`, `Architecture: Option B — Context-First with Adaptive Execution`, `Playwright Fallback (Slack + others)` to the rest of the system?**
  _26 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 10` be split into smaller, more focused modules?**
  _Cohesion score 0.13333333333333333 - nodes in this community are weakly interconnected._