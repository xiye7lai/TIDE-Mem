# Agent Memory Challenge 2026 申请表文案（可直接整理后粘贴）

> 提交前替换所有 `[方括号占位符]`。不要把 Eval Key、Leaderboard Key、Memory System Key 或模型供应商密钥写入此文件或 GitHub。

## 一、基础信息

**系统名称：** TIDE-Mem

**版本名称：** v0.1.0-amc2026

**参评类型：** Textual Memory / 文本记忆

**参赛组别：** Academic Methods / 学术方法榜

**提交路径：** 自行部署 Add / Search API

**联系人：** [YOUR NAME]

**联系邮箱：** [YOUR EMAIL]

**机构或团队：** [YOUR AFFILIATION OR TEAM]

**团队成员：** [TEAM MEMBERS; SOLO IF INDIVIDUAL]

**公开 GitHub 仓库：** [PUBLIC GITHUB REPOSITORY URL]

**固定 Commit SHA：** [FULL 40-CHAR COMMIT SHA]

**固定 Git Tag：** v0.1.0-amc2026

**Docker 镜像标识/摘要：** [IMAGE ID OR DIGEST]

## 二、API 信息

**Public Base URL：** [HTTPS PUBLIC BASE URL]

**Add URL：** [HTTPS PUBLIC BASE URL]/v1/memory/add

**Search URL：** [HTTPS PUBLIC BASE URL]/v1/memory/search

**Health URL：** [HTTPS PUBLIC BASE URL]/health

**鉴权方式：** X-Api-Key

**Memory System Key：** [仅在赛事受控密钥字段中填写，不要粘贴到普通说明文本]

**建议评测并发：** Max Add Concurrency = 16；Search Concurrency = 16；Top K = 100

**运行稳定性承诺：** 该固定版本将在提交后至少 30 天保持公网可访问；正式 Full 期间不静默修改代码、配置或检索行为。

## 三、方法简介（推荐提交版）

TIDE-Mem（Temporal, Identity-Isolated, Dual-view Evidence Memory）是一个面向长期 Agent 记忆的证据检索系统。其核心不是仅将对话写入向量库或仅保留摘要，而是同时维护两种互补视图：第一，逐消息保存不可变的原始对话证据及其会话、角色、消息索引和来源时间，确保精确名称、日期、数量、否定和来源不会因压缩而丢失；第二，使用赛事规定的 `gpt-4o-mini` 将对话提炼为自包含的结构化记忆卡，覆盖事实、事件、偏好、规则、计划、关系与状态更新。

对于可能变化的信息，TIDE-Mem 引入时间状态账本。结构化记忆可携带稳定的 `state_key`、事件时间和 set/cancel/complete 等更新类型；系统依据事件时间或来源时间重算当前状态，而不是简单把最后到达的请求视为最新事实，同时保留旧证据以支持历史、冲突和变化类问题。

在 Search 阶段，`gpt-4o-mini` 只生成“需要检索哪些证据”的计划，不生成最终答案；系统在严格 `user_id` 隔离下融合 FTS5/BM25、实体和时间精确匹配、时序与当前状态信号，并采用 reciprocal-rank fusion 获得候选。随后，`gpt-4o-mini` 仅返回候选证据 ID 及相关性评分，程序再进行覆盖度与多样性选择，从而为多跳、列表、计数和时间更新问题返回互补证据。Search 最终输出均来自已存储的原始证据或结构化记忆，不直接回答问题，也不选择选项标签。

系统通过同步事务保证 Add 在 HTTP 200 前已完成持久化并可立即检索；每条存储和检索路径均使用精确 `user_id` 作为硬边界。实现还包括 request_id 幂等、Token/Bearer/X-Api-Key 鉴权、公开 Health、Top K 约束、30 天自动清理、无正文日志、Docker 部署和合同/隔离测试。

## 四、原创性与来源披露

本次提交是为 Agent Memory Challenge 2026 独立实现的新系统。仓库未复制其他参赛者的记忆系统代码，不包含赛事私有数据、金标答案、公开题目硬编码或人工实时答题逻辑。

系统使用的通用开源依赖包括 FastAPI、Uvicorn、HTTPX、Pydantic，以及 Python/SQLite 提供的 SQLite FTS5。方法实现、提示词、数据库结构、时间状态账本、融合排序与覆盖选择均在公开仓库中完整披露。若提交前引入任何外部论文或仓库实现，将在 README 和方法文档中补充原作者、技术报告、原始链接与本次全部改动；当前版本无未披露的第三方记忆方法代码复用。

## 五、运行与复现说明

```bash
cp .env.example .env
# 在本地私密填写 TIDE_MEMORY_API_KEY 与 TIDE_LLM_API_KEY
docker compose up --build -d
python scripts/smoke_test.py \
  --base-url [HTTPS PUBLIC BASE URL] \
  --memory-key "$TIDE_MEMORY_API_KEY"
```

API 入口：

```text
GET  /health
POST /v1/memory/add
POST /v1/memory/search
```

依赖、环境变量、Docker、HTTPS 部署、测试和数据清理步骤均见仓库 README 与 `docs/DEPLOYMENT.md`。正式参评版本强制 `TIDE_LLM_MODEL=gpt-4o-mini` 且 `TIDE_ENFORCE_GPT4O_MINI=true`。

## 六、数据、安全与隐私说明

评测数据及其派生记忆仅用于完成本次评测，不用于训练、微调、产品分析、数据集重建或对外传播。应用日志不记录对话正文、问题、选项、检索证据或鉴权头。所有检索 SQL 都带精确 `user_id` 条件，不存在全局回退。系统默认在 30 天后自动删除记忆与 FTS 索引记录，备份遵循相同保留期。对话、问题、选项和候选文本在 LLM 提示中均被视为不可信数据，模型只允许输出结构化记忆、证据计划或候选 ID。

## 七、允许公开展示的信息

可公开展示：

- 系统名称：TIDE-Mem
- 版本：v0.1.0-amc2026
- 参评类型：Textual Memory
- 组别：Academic Methods
- 方法简介、公开仓库、固定 Commit/Tag、复现状态
- 经赛事审核后的总体及分项成绩
- 联系人/团队信息：[填写你同意公开的范围]

不可公开：Memory System Key、Eval/Leaderboard Key、模型供应商密钥、未公开评测数据、私有运行日志和数据库内容。

## 八、容量与已知限制

初始版本建议平台使用 Add 16、Search 16、Top K 100。HTTP 服务为异步实现，内部 `gpt-4o-mini` 调用由信号量限制为 16；SQLite 使用 WAL 和 60 秒 busy timeout。正式 Full 前会在实际供应商配额下完成公网 Smoke 和小规模并发验证。

当前版本采用单节点 SQLite，目标是可靠完成有限规模的统一评测，并非多区域商业服务。结构化抽取仍可能遗漏信息，因此系统保留不可变原始证据作为召回兜底。首个版本只申报 Textual Memory，不在截止前临时混入未经验证的 Coding Memory 分支。当前不宣称官方榜单成绩，待平台 Smoke/Full 完成后按审核结果报告。

## 九、Submission Notes（表单短文本）

Academic Methods / Textual Memory / self-hosted API submission. TIDE-Mem v0.1.0-amc2026 keeps immutable raw evidence plus gpt-4o-mini structured memory cards, maintains event-time-aware mutable states, and performs user-isolated hybrid retrieval with evidence-only planning/reranking and coverage-aware selection. Add is synchronous and idempotent; Search returns only stored evidence under the exact user_id. The public repository includes pinned dependencies, Docker, API entrypoints, tests, security/retention policy, and full reproduction instructions. Hosted endpoints will remain stable for at least 30 days. No benchmark labels, hard-coded answers, cross-user state, prompt injection, or human answering are used.
