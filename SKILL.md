---
name: weekly-report
description: Generate a concise, leader-facing daily or weekly work report from the user's coding-agent session activity — works with BOTH Claude Code and Codex transcripts (or aggregates user-provided team daily reports, extracting the user's own entries). Truncates to the chosen day or Monday–Sunday week; offers selectable output styles (详细/简约/要点); writes a terse report (做了什么 → 产出/结论 → 下一步) split 公司/个人, ending with a 风险同步 section; and self-evolves via a learned-preferences log and cross-week continuity. Trigger when the user asks for a 日报 / 周报 / daily report / weekly report, "what did I work on today/this week", or sends daily reports to roll up into a weekly.
---

# Daily / Weekly Report (日报 / 周报)

Build a human-readable work report from the user's Claude Code session history.
Two modes — **daily** (one day) and **weekly** (Mon–Sun) — share the same
requirements. Pipeline: **pick mode → collect → write report**.

Both modes follow `reference/report_principles.md`: every item is
**做了什么 → 产出/结论 → 下一步**, and must report the substantive conclusion, not
just a count of outputs (结论 > 数量). Read that file first — it is the quality bar.

## Step 1 — Pick the mode

- If the user said 日报 / daily / "today" → **daily mode**.
- If the user said 周报 / weekly / "this week" → **weekly mode**.
- **If the user provides daily reports and asks for a weekly** (发日报→生成周报) →
  **weekly-from-dailies mode**: skip Step 2 (collection); the supplied daily reports
  ARE the input (pasted text, or a file/path the user points to — Read it).
  Aggregate them per `reference/weekly_report.md` input option B
  (merge same-thread items across days into progression arcs, consolidate risks).
  Treat the dailies as the only source of truth; don't invent facts beyond them.
  - **If the dailies are a shared/team report (many people's entries), first do
    人物提取** (see `report_principles.md`): keep ONLY the target person's entries
    (the user by default — name/aliases from the user-identity memory or
    `project_categories.md`; or whoever the user names). Attribute by the name at
    the START of each entry; don't grab adjacent colleagues' lines or treat the
    person merely being mentioned as ownership.
- If ambiguous, ask which one (and which day/week) before collecting.

## Step 2 — Collect raw activity

The collector scans **both** Claude Code (`~/.claude/projects/*/*.jsonl`) and Codex
(`~/.codex/sessions/**/rollout-*.jsonl`) transcripts, truncates to the window
(local timezone), and emits a per-day digest as JSON. `--source claude|codex|all`
(default `all`) limits the source. Each thread carries a `source` field. Save to a temp file:

**Daily** (single day, defaults to today):
```bash
python3 ~/.claude/skills/weekly-report/scripts/collect_week.py --single-day > /tmp/report_raw.json
# a specific day:  --single-day --date 2026-05-28
```

**Weekly** (Mon–Sun, defaults to this week):
```bash
python3 ~/.claude/skills/weekly-report/scripts/collect_week.py > /tmp/report_raw.json
# last week:  --week-offset -1     a specific week:  --date 2026-05-20
```

The JSON has `mode`, `week_start`, `week_end`, `timezone`, and
`days[date] = [session…]`. Each session bucket carries `cwd`, `first_ts`/`last_ts`,
`user_prompts` (intent), `assistant_snippets` (outcomes), `tool_activity` (counts),
and `files_touched`. If `day_count` is 0, tell the user there was no activity in
that window and stop.

## Step 2.5 — Pick the output style

Before writing the full report (daily OR weekly — both apply), offer the output style
(see `reference/styles.md`): render the SAME representative item in the 3 styles
(正常版 / 简洁版 / 要点速览版) as a quick demo, then ask via AskUserQuestion which to use.
Default to the user's last choice in `learned_preferences.md` (else 正常版). Record the
chosen style back to `learned_preferences.md`. If the user already named a style, skip the ask.

## Step 3 — Write the report

Read `reference/report_principles.md` (the quality bar) first, then the mode prompt:
**Daily mode** → `reference/daily_report.md`; **Weekly mode** → `reference/weekly_report.md`.

Core rules (full detail in `report_principles.md`):
- **Concise — the leader grabs the point in ~3 sentences.** Each item ≈3 sentences
  (做了什么+结论含关键指标 / 一句补充 / 下一步或风险). Cut background prose and
  reasoning; keep conclusions, numbers, risks. Concision means dropping filler, NOT
  dropping conclusions.
- **Aggregate by initiative/thread, not by session.** Cluster sessions into real
  work threads; merge the same initiative's phases (e.g. build a feature → then
  monitor/measure it) and its cross-day progress into ONE item that tells the arc.
- **Each item: 做了什么 → 产出/结论 → 下一步.** Open with background/motivation, lead
  with the substantive conclusion (metrics, decisions, mechanism, impact), not a
  count of outputs (结论 > 数量). Next-steps must be concrete and prioritized.
- **Two self-contained reports — 公司 and 个人.** Each owns the FULL set of sections;
  ALL of 总结/本周完成/进行中/下周重点/风险同步 are written per-company and per-personal
  — never a single global 进行中/下周重点/风险同步 shared across both.
- **Use the standard report sections** (per `report_principles.md`): 总结 (1–2 sent
  throughline) → 本周完成 (by theme/project, ranked by importance, dense bullets with
  metrics + 相关 MR/Notion links with status; tables for eval data) → 进行中 → 下周重点
  → 风险同步. **Daily uses 今日完成 ONLY** (per-item 下一步; risks folded into 下一步) —
  no 进行中/下周重点/风险同步 sections (those are weekly-only).
- **Weekly ends with a mandatory 风险同步 section** consolidating the week's risks —
  not just security but mainly progress-type: 阻塞/延期/依赖/待确认/质量/成本/安全.
  Each: what's at risk + impact + mitigation/support needed. If none, say so; flag
  external causes (e.g. cluster maintenance) as external. (Daily: no such section.)
- **Split into 公司 vs 个人 reports.** Pre-classify with `reference/project_categories.md`
  (company/personal + tier prior), present accordingly, then proactively ask the
  user (AskUserQuestion) to confirm/adjust; write the answer back to that table.
- **Audience = technical leader.** Precise technical prose; keep professional terms
  and English terms as-is (don't translate); NO code-level field/variable/file
  names, commit hashes; no colloquial/dramatic phrasing; no hype ("最大短板"/"关键
  抓手"); no speculation ("怀疑…与 X 有关"). No overview section, no emoji in headings.
- **Don't fabricate; verify against evidence.** Before listing a next-step, check it
  isn't already done. Attach a link (MR/PR/Notion/doc) ONLY when evidence shows it
  is this item's actual artifact — never by mere co-occurrence in the same session.
  Don't expose raw session_ids or local file paths.

After rendering, offer to: switch mode (日报 ↔ 周报), regenerate for another
day/week, or save to a file.

## Step 4 — Deliver

The report is meant to be sent to a leader (human-readable, covering 工作内容 / 任务进度 /
可能风险). Two delivery rules:
- **The report body is the work itself** (产出 + 进展 + 结论 + 风险). MR/PR/Notion links are
  only trailing "相关：" support, never the headline.
- **When the report lives in a doc/Notion and is sent to the leader, include that link**
  (the leader explicitly wants 重点 +link). If you saved the report to a file/doc, surface
  its link/path at the top or bottom so it's one click to open.

## Self-evolution (do these every run)

The skill learns instead of being re-taught. Personal/evolving files live locally and
are gitignored (seeded from committed `*.example` files on first use — if a real file is
missing, copy its `.example`).

1. **Learned preferences** — BEFORE writing, read `reference/learned_preferences.md` and
   apply it (it OVERRIDES the generic rules on conflict; newest wins). AFTER the user
   corrects/rejects something or states a new preference, APPEND one line
   (`- [YYYY-MM-DD] <一句话可执行偏好>`) to that file so it sticks next time.
2. **Cross-week continuity** — at the START of a weekly, read `state/last_week.json` (per
   公司/个人: previous `进行中` + `下周重点`). Open each report with a brief
   **「上周计划完成情况」** that marks each prior item ✅完成 / 🔶部分 / ⬜未动 (cross-checked
   against this week's 本周完成), and carry unfinished ones into this week's 进行中/下周重点.
   At the END, write this week's `进行中`/`下周重点` (both categories) back to
   `state/last_week.json` for next time. (Daily mode skips this.)
3. **Self-critique before presenting** — run the checklist and FIX violations before
   showing the user: (a) same-initiative phases merged into one item (not two)?
   (b) each item ≈3 sentences, 总结 1 sentence? (c) team-report entries correctly
   attributed to the target person? (d) 公司/个人 fully separate, each with its own
   进行中/下周重点/风险同步? (e) every link is truly this item's artifact? (f) if the report
   may be shared/synced, real numbers/secrets/internal names desensitized?
4. **Growing example bank** — when the user approves a report ("这版可以"/"就这样"), save it
   to `examples/` (sanitized if it may leave the machine) and prefer the most recent
   approved example as the style anchor next time, above the canonical few-shot.

## Reference
- `reference/report_principles.md` — shared rules + the 结论>数量 quality bar.
- `reference/styles.md` — output style presets (正常/简洁/要点, apply to 日报+周报) + per-style demo.
- `reference/learned_preferences.md` — evolving, user-specific preference log (local).
- `reference/daily_report.md` — daily report prompt (tiered, event-aggregated).
- `reference/weekly_report.md` — weekly report prompt (cross-day progression merge).
- `reference/project_categories.md` — 公司/个人 + 主线/调研/支线 classification priors.
