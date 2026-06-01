# 周报 skill（weekly-report）

一个 [Claude Code](https://claude.com/claude-code) skill（也兼容 [Codex](https://developers.openai.com/codex/)）：
读取本机的 Claude Code / Codex 会话记录，按**单日**或**周一至周日**截断，自动生成**给技术型 leader 看**的可读日报 / 周报。

## 它做什么

- **数据源（双源）**：扫描 Claude Code（`~/.claude/projects/*/*.jsonl`）与 Codex
  （`~/.codex/sessions/**/rollout-*.jsonl`）的本机 transcript，按本地时区切到指定的一天/一周，
  按天分组抽取信号（意图、产出要点、改动文件、工具活动、可追溯链接）。也可直接喂团队日报（自动按本人姓名抽条）。
- **两种模式**：日报（单日）/ 周报（Mon–Sun），要求一致。
- **可选风格**：生成前可选 详细 / 简约 / 要点速览 三种风格（见 `reference/styles.md`）。
- **结构**：报告分**公司 / 个人**两份；每份 总结 → 本周完成（按主题、按重要性）→ 进行中 → 下周重点 → 风险同步。
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

## 自进化（越用越懂你）

skill 会从反馈里学习，而不是每次重新教：

- **学习偏好回路**：`reference/learned_preferences.md` 是一份偏好日志，优先级高于通用规则。你每次纠正/表达
  新偏好，模型就追加一条，下次自动生效。
- **跨周连续性**：`state/last_week.json` 存上周的「进行中/下周重点」；本周开头自动给出「上周计划完成情况」
  并继承未完成项，报告从快照变连续线程。
- **生成后自查自修**：出报告前强制走硬清单（同主线合并、≤3 句、人物归属、公司/个人分开、链接核实、对外脱敏），
  违反就改了再给你。
- **成长型 few-shot**：你认可的报告会存进 `examples/` 作为下次风格锚点。

> 以上"会被写入/含个人数据"的文件（`learned_preferences.md`、`project_categories.md`、`state/`、`examples/`）
> 都**本地保存、已被 gitignore**；仓库只放对应的 `*.example` 模板。**首次使用**：把 `*.example` 复制成去掉
> `.example` 的同名文件即可（skill 也会在缺失时自动从模板初始化）。

## 结构

```
SKILL.md                              编排：选模式 → 采集 → 写报告 + 自进化
scripts/collect_week.py               采集器（按周/单日截断、分叉去重、头尾抓取、链接抽取、密钥脱敏）
scripts/extract_person.py             团队日报→确定性抽取本人条目（防张冠李戴，用于"发团队日报生成本人周报"）
reference/report_principles.md        共用核心原则（结论>数量、三段式、聚合、极简、可读性、风险同步、人物提取…）
reference/daily_report.md             日报 prompt
reference/weekly_report.md            周报 prompt（含脱敏 few-shot 范例）
reference/styles.md                   输出风格预设（详细/简约/要点，生成前可选）
reference/judge.md                    质量评分标准（周报四维打分 / 日报逐条评级+修改版；自查与按需评审）
reference/project_categories.example.md   公司/个人 + 本人身份 归类模板（复制为 project_categories.md 使用）
reference/learned_preferences.example.md  自进化偏好日志模板（复制为 learned_preferences.md 使用）
（本地生成、不入库：project_categories.md、learned_preferences.md、state/、examples/、*.json）
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
- **个性化/自进化文件本地化**：`project_categories.md`、`learned_preferences.md`、`state/`、`examples/`
  含个人/内部信息，均**本地保存、已 gitignore**；仓库只有 `*.example` 模板，不会回传你的真实配置。
- **本仓库不含任何会话数据**：只有 skill 代码、prompt 与模板。

## 说明

- 报告完全基于本机会话记录、本地生成，skill 本身**不外传**任何数据。
- 数据源、归类配置都可按需修改。
