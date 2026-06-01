# 周报 skill（weekly-report）

一个**给技术型 leader 看**的日报 / 周报生成 skill，**Claude Code 与 Codex 通用**（同一套 `SKILL.md`）。
它读取本机的 coding-agent 会话记录，或你贴进来的团队日报，自动产出结构清晰、结论优先、可读性强的工作报告。

---

## 能做什么（4 种用法）

| # | 用法 | 怎么触发 | 说明 |
|---|---|---|---|
| 1 | **自动生成日/周报** | "出今天日报""出本周周报""出上周周报" | 读 Claude Code + Codex 会话，按单日 / 周一至周日截断 |
| 2 | **团队日报 → 本人周报** | 贴团队日报（或给文件路径）+ "生成我的周报" | 先用脚本**确定性抽出本人条目**（防张冠李戴），再聚合成周报 |
| 3 | **给报告打分（judge）** | 贴一份日/周报 + "评一下 / 打分" | 按固定维度评分 + 指出问题 + 给修改版 |
| 4 | **生成时自带质量自查** | 在 1、2 过程中 | 内部自查自修恒做；**是否展示评分**首次问一次、记住后不再问 |

---

## 核心特性

- **双源采集**：同时读 Claude Code（`~/.claude/projects`）与 Codex（`~/.codex/sessions`）的本机会话；按本地时区切到指定日/周，抽取意图、产出要点、改动文件、工具活动、可追溯链接。
- **公司 / 个人分开**：两份独立报告，各自完整。
- **周报结构**：总结 → 本周完成（按主线/调研/支线，按重要性排序）→ 进行中 → 下周重点 → 风险同步。
- **日报结构**：只有「今日完成」（下一步/风险并进条目）。
- **三段式 + 结论>数量**：每条 = 做了什么 → 产出/结论 → 下一步；只报数量不报结论判为不合格。
- **三档风格**（生成前可选，记住偏好）：正常版 / 简洁版 / 要点速览版。
- **技术 leader 文风**：保留专业 / 英文术语，不出现代码级字段，不口语、不吹捧、不臆测。
- **聚合不堆叠**：同一主线的不同阶段（功能→实测）合并成一条；**跨源（Claude/Codex）同一件事去重合并、正文不标来源**。
- **人物提取防张冠李戴**：团队日报按"行首人名切块"，只留本人的块（含本人在列的协作条），跨多天，确定性、宁漏不错。
- **MR 只作 support**：正文讲工作内容/产出/进展/风险，MR/链接仅在条目末尾"相关："佐证；发 leader 时带 doc/Notion link。
- **质量评分（judge）**：周报四维（完整性 / 数据支撑 / 叙事清晰度 / 风险意识）；日报逐条评级 + 建议修改版。
- **密钥脱敏**：采集器对会话里的 API key / token / 密码做 best-effort 脱敏。
- **自进化**：从你的纠正里学习（`learned_preferences`）、跨周连续性、生成后自查自修、成长型 few-shot。

---

## 安装（Claude Code 与 Codex 通用）

```bash
git clone <this-repo> weekly-report

# Claude Code
cp -r weekly-report ~/.claude/skills/weekly-report

# Codex（VSCode Codex 插件 / CLI；CODEX_HOME 未设时默认 ~/.codex）
cp -r weekly-report ~/.codex/skills/weekly-report
```

> **想两个工具共用一份**（自进化偏好/配置不分叉）：装在一处，另一处软链接过去：
> `ln -s ~/.claude/skills/weekly-report ~/.codex/skills/weekly-report`。
> SKILL.md 里脚本用相对路径（`scripts/…`），两个位置都能解析。
> 若 Codex 不识别软链接，改用上面的实拷贝即可。

### 首次配置（个人化，本地不入库）
```bash
cd <skill 目录>/reference
cp project_categories.example.md project_categories.md   # 填本人身份 + 公司/个人项目归属
cp learned_preferences.example.md learned_preferences.md  # 可留空，之后自动积累
```

---

## 在 VSCode Codex 插件里使用

Codex 的 skill 是**描述触发、自动发现**的——没有专门命令，用自然语言描述任务即可。

1. **重载让 Codex 发现 skill**（新装的必须）：`Cmd+Shift+P` → "Reload Window"，或重开 Codex 会话。
   （Codex 官方说法：*Restart Codex to pick up new skills*。）
2. **确认已发现**：在 Codex 里问 "你有没有 weekly-report skill？" 能列出即成功。
3. **自然语言触发**，例如：
   - `出我今天的日报` / `生成本周周报` / `出上周周报`
   - `把这份团队日报总结成我的周报`（贴团队日报或给文件路径）
   - `评一下这份周报质量`（贴报告）
4. 脚本读本地会话文件时 Codex 可能弹**沙箱授权**，同意即可。

## 在 Claude Code 里使用
直接说"出本周周报 / 今天日报 / 把团队日报生成我的周报 / 评一下这份日报"即可，Claude 按 description 触发。

---

## 设计原则（核心质量约束）

- **结论 > 数量**：必须给指标、决策、机制、影响，而非"做了 N 条"。
- **按主线/事件聚合**：同一件事的不同阶段合并成一条讲来龙去脉，不按会话/不按天拆。
- **技术 leader 视角**：精准技术书面语，专业/英文术语保留，无代码字段、无口语、无吹捧、无臆测。
- **不杜撰、对照证据**：内容可追溯到会话证据；下一步先核对是否已做过；链接只在确属本条产物时附。
- **防张冠李戴**：团队日报严格按行首人名归属，成稿前逐条核对，宁漏不错。

## 自进化（越用越懂你）
- **学习偏好**：`reference/learned_preferences.md` 优先级高于通用规则；你每次纠正就追加一条、下次自动生效。
- **跨周连续性**：`state/last_week.json` 存上周「进行中/下周重点」，本周开头自动给「上周计划完成情况」。
- **生成后自查自修**：出报告前按 `judge.md` 维度内部打分、修掉短板再给你。
- **成长型 few-shot**：你认可的报告存进 `examples/` 作风格锚点。

> 以上"会被写入/含个人数据"的文件（`learned_preferences.md`、`project_categories.md`、`state/`、`examples/`）
> 均**本地保存、已 gitignore**；仓库只放 `*.example` 模板。

---

## ⚠️ 安全与同步风险

skill 只读取**指定时间范围内**（单日或本周）的会话，但该范围内仍可能粘贴过 API key、密码、内网地址等敏感信息：

- **密钥脱敏是 best-effort、非 100%**，不要依赖它处理高敏数据。
- **不要把采集器输出的 `*.json` 或未审阅报告 commit/同步**到任何仓库（`.gitignore` 已忽略）。
- 报告含内部信息，**外发前自行审阅、按需脱敏**；公开仓库里的示例/few-shot 一律用占位符。
- 本仓库**不含任何会话数据**，只有 skill 代码、prompt 与模板。

---

## 目录结构

```
SKILL.md                              编排：选模式 → 采集 → 写报告 → 自查/judge → 投递；含 4 种用法
scripts/collect_week.py               双源采集器（按周/单日截断、分叉去重、头尾抓取、链接抽取、密钥脱敏）
scripts/extract_person.py             团队日报→确定性抽取本人条目（防张冠李戴）
reference/report_principles.md        核心原则（结论>数量、三段式、聚合、可读性、风险同步、人物提取、借鉴优秀写法…）
reference/daily_report.md             日报 prompt（今日完成）
reference/weekly_report.md            周报 prompt（五板块 + 脱敏 few-shot 范例）
reference/styles.md                   输出风格预设（正常/简洁/要点）
reference/judge.md                    质量评分标准（周报四维 / 日报逐条 + 修改版）
reference/project_categories.example.md   公司/个人 + 本人身份 归类模板
reference/learned_preferences.example.md  自进化偏好日志模板
（本地生成、不入库：project_categories.md、learned_preferences.md、state/、examples/、*.json）
```
