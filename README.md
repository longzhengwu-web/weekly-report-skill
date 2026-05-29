# 周报 skill（weekly-report）

一个 [Claude Code](https://claude.com/claude-code) skill：读取本机的 Claude Code 会话记录，
按**单日**或**周一至周日**截断，自动生成**给技术型 leader 看**的可读日报 / 周报。

## 它做什么

- **数据源**：扫描 `~/.claude/projects/*/*.jsonl`（本机所有项目的会话 transcript），
  按本地时区切到指定的一天或一周，按天分组并抽取信号（用户意图、产出要点、改动文件、工具活动、可追溯链接）。
- **两种模式**：日报（单日）/ 周报（Mon–Sun），要求一致。
- **结构**：报告分**公司 / 个人**两份；每份按**主线 / 调研·设计 / 支线·协作**分层，按重要性排序。
- **每条三段式**：做了什么 → 产出/结论 → 下一步。

## 设计原则（核心质量约束）

- **结论 > 数量**：只报"做了多少"不报"得出什么结论"不合格——必须给指标、决策、机制、影响。
- **按主线/事件聚合**：同一件事的不同阶段（如"做功能 → 上线实测/监控"）合并成一条讲来龙去脉，不按会话拆。
- **技术型 leader 视角**：精准技术书面语，保留专业 / 英文术语，不出现代码级字段/变量/文件名，不口语、不吹捧、不臆测。
- **不杜撰、对照证据**：内容可追溯到会话证据；下一步先核对是否已做过；链接只在确属本条产物时附。

## 用法

安装后（见下），在 Claude Code 里直接说：

```
出本周周报          # 本周 Mon–Sun
出上周周报
出今天的日报
出 2026-05-28 的日报
```

或直接跑采集器拿原始数据：

```bash
# 本周（Mon–Sun）
python3 scripts/collect_week.py
# 上周
python3 scripts/collect_week.py --week-offset -1
# 单日（默认今天）
python3 scripts/collect_week.py --single-day
# 指定某天 / 指定某周
python3 scripts/collect_week.py --single-day --date 2026-05-28
python3 scripts/collect_week.py --date 2026-05-20
```

采集器输出 JSON：`mode` / `week_start` / `week_end` / `timezone` / `days[date] = [thread…]`，
每个 thread 含 `user_prompts`、`assistant_snippets`（含会话结尾结论）、`tool_activity`、
`files_touched`、`links`（MR/PR/Notion/文档等可追溯链接）；分叉会话已按首条实质 prompt 去重合并。

## 安装

复制到 Claude Code 的 skills 目录：

```bash
git clone <this-repo> weekly-report
cp -r weekly-report ~/.claude/skills/weekly-report
```

## 结构

```
SKILL.md                          编排：选模式 → 采集 → 写报告
scripts/collect_week.py           采集器（按周/单日截断、分叉去重、头尾抓取、链接抽取）
reference/report_principles.md    共用核心原则（结论>数量、三段式、聚合、可读性、链接核实…）
reference/daily_report.md         日报 prompt
reference/weekly_report.md        周报 prompt
reference/project_categories.md   公司/个人 + 主线/调研/支线 的归类先验（用户可维护）
```

## ⚠️ 安全与同步风险（重要）

这个 skill 只读取**指定时间范围内**（单日或本周）的 Claude Code 会话，不是全部历史。但该范围内的
会话里仍可能粘贴过 API key、token、密码、内网地址等敏感信息。使用与同步前请注意：

- **密钥脱敏**：采集器已内置 best-effort 脱敏，会把常见密钥/令牌/密码（`sk-…`、`gh*_…`、
  `AKLT…`、JWT、以及 `password/secret/token/api_key/密码：…` 形式的值）替换为 `[REDACTED]`。
  但这是尽力而为、非 100% 兜底，**不要依赖它处理高度敏感数据**。
- **不要提交会话数据 / 中间产物**：采集器输出的 JSON 与生成的报告可能仍含敏感信息或公司内部内容。
  **切勿把 `*.json` 原始数据或未经审阅的报告 commit/同步到任何仓库**（本仓库 `.gitignore` 已忽略它们）。
- **报告含公司内部信息**：生成的日/周报会包含指标、MR/Notion 链接、项目名等。**外发前自行审阅、按需脱敏**。
- **个性化配置**：`reference/project_categories.md` 是个人/公司归属配置。本仓库内是**通用模板**；
  你本机改写后的真实版本含内部信息，**不要回传到公开仓库**。
- **本仓库不含任何会话数据**：只有 skill 代码与 prompt。

## 说明

- 报告完全基于本机会话记录、本地生成，skill 本身**不外传**任何数据。
- 数据源、归类配置都可按需修改。
