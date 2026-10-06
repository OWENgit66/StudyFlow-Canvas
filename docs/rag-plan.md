# StudyFlow RAG Readiness Audit

> Historical pre-RAG readiness audit. For the implemented system, see [Architecture](architecture.md), [RAG pipeline](rag-pipeline.md) and [current scope](roadmap.md). Statements about missing features below describe the audit date.

审计日期：2026-09-25。范围：现有代码、数据库结构和只读汇总检查；只做分析与规划。本文件中的新增表、服务、API 和开发步骤均为建议，尚未实现。

**结论：已有可复用的原文 chunks、课程归属、页码、解析警告和 LLM provider 边界。最小接入点是 `DocumentChunk`，无需重建 Canvas → PDF → Knowledge 管线。先确认可索引数据的新鲜度，再做单课程检索；SQLite 可以继续作为第一版存储。**

## 1. 当前真实数据流

```text
Dashboard / Course / Week 的 Sync 按钮
  → POST /api/sync?background=true
  → SyncService：当前学期筛选、可选 Course / Module / File scope
  → CanvasService：Courses → Modules → Module Items
       ├─ File：Canvas File ID
       └─ Page：读取 HTML，提取文件链接及 Page/link/nearby metadata
                 → Canvas 文件，或受限制的 external PDF 路径
  → 合并重复发现；阅读材料过滤；resource_type 分类
  → 按 Canvas 文件更新时间 / external revision 判断 NEW / UPDATED / UNCHANGED
  → Course / Week upsert，Resource 创建或 metadata 更新
  → download_resource：写入本地 materials，保存 Resource.local_path
  → process_resource
       → DocumentService.parse → 按页提取、清洗、质量检测
       → DocumentService.chunk → document_chunks
       → Resource.parsing_report
  → KnowledgeService.generate
       → 读取存储 chunks、核验 PDF 与解析结果
       → AIService.extract → Provider → JSON/schema/来源/公式校验
       → SemanticSupportService：额外的模型支持性审查
       → ResourceKnowledge + Concept / Question / Week Summary
  → frontend 读取资源和当前 knowledge，展示学习内容与原 PDF 页码链接
```

主要依据：

- [api/sync.py](../backend/app/api/sync.py) 与 [SyncService](../backend/app/services/sync_service.py)：单进程后台任务、分阶段提交、失败隔离、取消与增量恢复。
- [repositories/sync.py](../backend/app/repositories/sync.py)：课程/Week 映射与增量判定。只改变类型不改变文件时间戳，也不使 knowledge 失效。
- [page_materials.py](../backend/app/services/page_materials.py)：Canvas Page HTML 用于发现资料和获取分类上下文；**没有把整篇 Canvas Page 正文作为学习文档存入 chunks**。
- [material_service.py](../backend/app/services/material_service.py)：文件存储复用现有 Semester/Course/Week 路径管理。
- [document_processing.py](../backend/app/services/document_processing.py)：成功解析后替换该 Resource 的 chunks 并保存健康报告；失败时可能保留旧 chunks。
- [week-page.tsx](../frontend/src/components/week-page.tsx) 与 [learning-content.tsx](../frontend/src/components/learning-content.tsx)：读取资源及非 stale 的 canonical knowledge，而非现场调用模型。

未变且已完成的文件跳过下载、解析和 AI；已解析但 knowledge 失败的文件可从知识阶段恢复。非 PDF 文件可能已经下载，但目前 parser 只支持 PDF。阅读过滤与 lecture/tutorial/other 是两个不同职责；`other` 不等于“必须忽略的阅读”。

## 2. 数据库与原始文本现状

以下字段已对照 ORM 和本地 SQLite 的只读 `PRAGMA table_info`；只检查结构与统计，没有输出课程正文、文件名或凭据。

| 表 | 与 RAG 相关的现有字段 | 定位 |
|---|---|---|
| `courses` | `id, semester_id, canvas_course_id, code, name`，时间戳 | 必须限定的课程范围 |
| `weeks` | `id, course_id, week_number, title, canvas_module_id`，时间戳 | 可选 Week/Module 过滤 |
| `resources` | `id, week_id, canvas_file_id, external_source_key, external_revision, filename, file_type, resource_type, local_path, canvas_updated_at, sync_status, sync_stage, parsing_report`，时间戳 | 文件身份、类型、处理状态与解析健康 |
| `document_chunks` | `id, resource_id, page_number, chunk_index, content, created_at` | **主要 RAG 原文来源** |
| `resource_knowledge` | `resource_id` 主键、`payload` JSON、`source_fingerprint, provider, model`，时间戳 | 每个资源的 canonical AI 输出；不是主要检索语料 |
| `summaries` | `id, week_id` 唯一、`overview, key_points, exam_focus`，时间戳 | Week 汇总投影；后两者存 JSON 字符串列表 |
| `concepts` | `resource_id, week_id, name, definition, explanation, importance, source_page` 等 | AI 概念投影，单个首来源页 |
| `questions` | `resource_id, week_id, question, answer, source_page` 等 | AI 问题投影，单个首来源页 |

模型见 [models](../backend/app/models/)。完整的多 chunk、多页引用、证据与审查信息保存在 `ResourceKnowledge.payload`，不能仅用 Concept/Question 的单页投影恢复完整来源。Formulas、examples、exam focus 等也在 payload 中，没有各自独立的业务表。

`DocumentChunk` 已有 `(resource_id, chunk_index)` 唯一约束、正数页码、非负序号。`chunk_index` 是资源内从 0 开始的序号；`page_number` 是 PDF 从 1 开始的实际页面位置。课程、Week、类型通过 `DocumentChunk → Resource → Week → Course` join 获得，不必复制进原 chunks 表。

本次只读快照：171 个 Resources；114 个资源有 chunks，总计 4,091 个非空 chunks；104 条 canonical resource knowledge；82 个资源的 `parsing_report` 非空。Chunks 长度为 6–2,000 字符，平均约 1,114 字符。Chunk → Resource → Week → Course 未发现孤立关联。**这些数量不表示所有 chunks 已通过索引新鲜度和质量检查**；本次没有打开 PDF 检验报告 fingerprint，也没有进行完整数据库验收。

### 文本在哪里提取、保存

- [document_quality.py](../backend/app/services/document_quality.py) 的 `extract_page` 同时调用 PyMuPDF `get_text("text", sort=True)` 和 structured `get_text("dict", ...)`，得到 raw text 与 span 布局信息。
- [schemas/document.py](../backend/app/schemas/document.py) 的 `ParsedPage` 在解析结果中保留 `raw_text`、`text/cleaned_text`、spans 和 warnings。重复页眉页脚清理作用于 cleaned text。
- [document_chunking.py](../backend/app/services/document_chunking.py) 已完成按段落/行/句子/词边界分块，默认 2,000 字符、200 字符 overlap；逐页调用，因此不跨页。配置单位是字符，不是 token。
- 清洗后原文以 `DocumentChunk.content` 持久化。Raw text、完整逐页 cleaned text 和 spans **没有独立持久化表**；它们主要存在于当次解析结果中。重叠 chunks 不能简单拼接后当成完整、无重复的原页文本。
- `Resource.parsing_report` 保存紧凑页级问题与源文件 fingerprint；不保存整页原文或布局。
- 原 PDF 保存在本地 material storage。`GET /api/resources/{id}/chunks` 直接分页读取数据库，不重新解析；`GET /api/resources/{id}/file` 返回经过路径校验的已注册文件。

因此第一版 RAG 可以直接索引现有 chunks，无须再次全量 chunking。若以后修改分块策略，需要有版本和定向重建方案；不能用这次 RAG 接入偷偷重分全部文件。缺少报告、旧报告或文本不可信的资源要明确列为待验证，不能默认为健康。

## 3. 当前可以复用的组件

| 组件 | 可复用内容 | 边界 |
|---|---|---|
| SQLite / SQLAlchemy / `get_db` | Session、事务、关联查询、加法式迁移模式 | 不创建新的数据库服务 |
| DocumentService + DocumentChunk | 持久化原文、页码、已有分块 | 不在每次问答中重解析 |
| Parsing health / symbolic safety | 页级警告、fingerprint、不可读符号检测、警告公式遮蔽 | 旧报告可能缺失；不能将“无报告”当作“无风险” |
| `LLMProvider.generate(system, user, schema)` + factory | 模型配置、OpenAI/DeepSeek 切换、传输层错误处理 | 没有 embedding 接口；RAG 自己负责 bounded retry 与回答校验 |
| 现有 grounding 逻辑 | chunk 白名单、页码匹配、应用侧生成证据的设计 | 现有 `source_map` 限定单 Resource，不能原样用于跨资源的课程问答 |
| API 与前端来源链接 | `fileURL(resource_id, page)`、`SourceReference`、课程/Week 导航 | RAG 引用元数据必须由服务端可信记录构建 |
| 增量同步策略 | 文件身份、更新时间、角色 metadata 单独更新 | 索引必须有自己的新鲜度，不依赖 knowledge 是否生成成功 |

### Knowledge generation 实际工作方式

入口是 [KnowledgeService.generate](../backend/app/services/knowledge_service.py)。输入来自该 Resource 的数据库 chunks（id、页码、content），再重新解析当前 PDF 取得 warnings，并比对当下生成的 chunks 与已存储 chunks。随后释放读取事务，由 [AIService](../backend/app/services/ai_service.py) 做输入遮蔽、有限批次、有限重试、严格 Pydantic/schema 与来源验证、公式约束和 semantic review。

输出为 `ExtractionResult`：topic、overview、concepts、key points、formulas、examples、exam focus、questions，以及来源证据、过滤统计、审查结果与 usage。Topic/overview 在校验与审查过程中由保留的条目重建，并非直接信任最初的无引用输出。

Factory 支持 OpenAI Responses API 与 DeepSeek Chat Completions JSON Output，模型从 `LLM_MODEL` 获取；不是硬编码选择。本地已存储 knowledge 的 provider/model 为 `deepseek / deepseek-flash`，这是历史记录，不代表本次发起了调用，也不保证运行进程仍使用相同配置。

[repositories/knowledge.py](../backend/app/repositories/knowledge.py) 按 `resource_id` 原子替换 canonical payload，重建 Concept/Question，再汇总该 Week 的当前资源到 Summary。保存前重新检查源 fingerprint；历史输出可保留但标为 stale。

**未来 RAG 不应调用 `KnowledgeService.generate` 或 `AIService.extract` 来回答用户问题**：它们是整份资料的知识提取流程。复用 provider、底层符号安全工具与校验原则，为问答另建小型服务和 schema。

## 4. 当前缺少的 RAG 组件

代码、依赖声明、API 和现有表检索结果：

| 能力 | 当前是否存在 |
|---|---|
| 原文 chunking、存储和按资源读取 | **有** |
| 原文 page/span extraction、质量检测 | **有**；完整 layout/page 原文未独立落库 |
| Embedding provider / embedding generation | **没有** |
| Embedding 数据表、向量索引或向量数据库 | **没有** |
| Vector search / semantic search / query-based retrieval | **没有** |
| FTS/BM25 检索实现 | **没有** |
| RAG query API、回答 schema、问答 UI | **没有** |
| `DocumentPage` 表、持久化页截图 | **没有** |

`SemanticSupportService` 是让模型审查已生成条目是否被给定证据支持，**不是语义搜索**。`list_chunks` 是按资源和序号查询，**不是相关性检索**。不应把二者计为已有 RAG。

还缺少：索引状态与失效处理、embedding 模型/版本/维度记录、课程过滤后的 top-k 检索、回答引用校验、无证据拒答、检索评测集与问答端预算。

## 5. 推荐的最小 RAG MVP 架构

先做**单次、单课程、文本问答**。不加入对话 Memory、Agent、工具调用、MCP、Vision 或跨课程查询。

```text
离线/显式索引：
  Existing DocumentChunks + current parsing warnings + source identity
    → 检查可索引性和 source/chunk fingerprint
    → 只为缺失或失效条目生成 embedding
    → SQLite 中的 additive embedding 表

在线问答：
  Course 页面的问题 + 可选 Week + resource_types
    → 校验课程、Week 归属、类型与长度限制
    → SQL join 先限定 Course / Week / type / 有效索引
    → Query embedding（没有候选时直接返回无证据）
    → RetrievalService：相同模型空间内 cosine top-k
    → 去重、上下文预算、关联源警告
    → RAGService → 现有 LLMProvider
    → Pydantic + 引用白名单 + 页面/资源/版本校验 + 公式安全
    → Answer 或 insufficient_evidence + 服务端构建的 Sources
    → 复用 PDF #page 链接
```

### SQLite 与 embedding 存储建议

当前语料规模可先采用 SQLite 保存向量数据，按课程筛选后在应用内精确计算 cosine top-k。无需 PostgreSQL、pgvector、外部向量库或队列。真实延迟和内存仍需在后续实现中测量，不能由行数直接宣布性能达标。

新增一个 `chunk_embeddings` 表即可作为起点：`chunk_id` 外键、`chunk_content_hash`、源/索引 fingerprint、embedding provider/model/revision、维度、向量、输入准备版本、时间戳。MVP 可用 SQLAlchemy JSON 存有限长度数值数组，并严格检查维度、有限数值和模型一致性；以后性能确有瓶颈再改变向量存储/检索实现。索引版本需绑定原文与警告处理策略，而不只是 chunk ID。

生成模型与 embedding 模型是独立配置。当前 `LLMProvider` 只有文本 JSON 生成接口，不能假定 DeepSeek chat 模型可直接用于 embedding。后续单独选择 embedding 实现与配置，保留现有生成 provider 接口；本次不选新服务、不下载模型、不安装依赖。

初期以显式单课程索引命令接入，避免改动 SyncService。成功重新解析后的旧索引必须被删除或判为失效；在新索引准备好前不得召回旧内容。耗时 embedding 调用不能持有 SQLite 写事务，写入前复查源版本。`resource_type` 通过实时 join 过滤，仅类型改变不应重新 embedding。

### resource_type 过滤

- 支持 `['lecture']`、`['lecture', 'tutorial']`、或三个类型全选；只接受现有枚举。
- 默认单课程内包含所有类型，类型过滤为用户显式选择。当前类型统计为 lecture 10、tutorial 9、other 152；历史默认值和不确定分类仍较多。默认排除 other 会漏掉大量可能有效的原文。
- 不将 query 自动判成 lecture/tutorial，不新增 classifier 或 confidence 功能。
- 筛选作用于 Resource 关联列，不改原文、不触发下载/解析/knowledge。
- Course scope 必须在选取 top-k 前执行，并在引用返回前再验证。选择 Week 时必须确认它属于该 Course；候选为空不得放宽到其他课程。

### 来源与安全契约

建议 API 为 `POST /api/courses/{course_id}/query`，请求含 `question`、可选 `week_id`、可选 `resource_types`。响应含 answer、insufficient_evidence 和 sources（chunk_id、resource_id、course_id、week_id、filename、page_number、短摘录、warnings）。这只是规划，不是现有 endpoint。

模型仅返回回答和检索白名单内的引用 ID，不负责生成文件名、文件路径、URL 或页码；服务端用同一版本的数据库记录补齐来源。必须拒绝无效/越界/跨课程引用，以及来源在回答期间发生变化的结果。ID 正确仍不等于回答受支持；需要含无答案、错误归因和不支持推论的离线问答案例。原有整份知识抽取的 semantic review 不能直接套用到回答 schema。

从匹配的 parsing report 按页传递警告，复用符号遮蔽/不可读内容检测；缺失、stale 或不可信警告状态采用保守策略。对危险公式拒绝猜测或修复，必要时返回原页链接并说明文本不足。将检索文本视为不可信数据，不能执行其中指令。有限 top-k、总输入预算、输出长度和 bounded retry 均由应用约束。

## 6. 推荐开发顺序

每一步单独验收，不一次实现全链路。

| 步骤 | 最小交付 | 验证重点 |
|---|---|---|
| RAG Step 1：Corpus readiness / 来源契约 | 读取现有 chunks，join 课程/Week/type；输出 eligible / missing / stale / review 状态；定义检索输入与来源 schema | 不改 chunks，不生成知识；课程隔离、空数据、缺失报告、错误版本测试 |
| RAG Step 2：单课程增量索引 | 加法式 embedding 表、独立 provider 边界、显式索引命令；直接复用现有 chunks | fake embeddings 测试；未变跳过、内容/模型/警告版本变化重建、失败回滚、chunk 替换失效、类型变化不重算 |
| RAG Step 3：只检索，不回答 | RetrievalService：数据库 prefilter、cosine top-k、去重、返回可信 sources；建立小型独立 retrieval eval | 命中来源页、跨课程零泄漏、Week/type 过滤、空结果、模型维度一致；先不调用生成模型 |
| RAG Step 4：最小 query API | RAGService + 回答 schema + 路由，复用现有文本 provider | mock provider；空证据拒答、引用白名单、源变更、公式警告、注入文本、超时和有限重试 |
| RAG Step 5：Course 问答 UI | Course 内 Ask this course、可选筛选、回答与可点击 sources | 保留 Dashboard/Week 原结构；loading/error/无证据状态、正确 PDF 页链接 |

**不需要新增“从零生成所有 chunks”的阶段。** Step 1 首先确认存储语料能否使用；只对明确缺失/过期的资源另行安排有界修复。DocumentPage、截图、OCR、Tutorial 专用 knowledge pipeline 不是文本 RAG MVP 的强制前置，但其缺失限制图表/扫描页问答能力。

当前 classification development/regression 和 pending holdout 保持独立，不拿它们代替 retrieval eval，不因 RAG 开发改标签或 classifier。

## 7. 预计文件改动（未来，按步骤引入）

### 可能修改的现有文件

- `backend/app/repositories/document_chunks.py`：课程范围 chunk 查询；未来成功替换 chunks 时处理关联索引生命周期。
- `backend/app/services/document_processing.py`、`backend/app/services/parsing_health.py`：若 Step 1 确认需要，在成功解析时记录 chunk 集/解析版本与报告的对应关系；优先扩展已有 JSON，不重建数据库。
- `backend/app/models/__init__.py`、`backend/app/core/schema_upgrade.py`：注册新增 embedding 表和必要加法式升级；沿用现有初始化机制。
- `backend/app/core/config.py`、`.env.example`：后续 embedding 独立配置、检索与问答预算；只有空白凭据占位。
- `backend/app/main.py`：Step 4 注册 RAG router。
- `frontend/src/lib/api.ts`、`frontend/src/lib/types.ts`、`frontend/src/components/course-page.tsx`：Step 5 接入 query 和来源显示。
- 依赖清单只在 embedding 实现选定且确实需要时修改。CanvasService、classifier、Holdout Eval、现有 knowledge 生成规则均无需为本计划改变。

### 建议新增的文件

- Step 1：`backend/app/schemas/rag.py`、`backend/app/repositories/retrieval.py`（已有 chunk query 可委托复用）。
- Step 2：`backend/app/models/chunk_embedding.py`、`backend/app/services/embedding_provider.py`、`backend/app/services/indexing_service.py`、`backend/app/index_course.py`。
- Step 3：`backend/app/services/retrieval_service.py`、`backend/evals/retrieval.py`（真实评测数据仍在 Git 忽略的 data 目录）。
- Step 4：`backend/app/services/rag_service.py`、`backend/app/api/rag.py`。
- Step 5：`frontend/src/components/course-query.tsx`；来源链接尽量复用已有组件。
- 分步增加 `test_retrieval_corpus.py`、`test_indexing.py`、`test_retrieval.py`、`test_rag.py` 与前端 query 测试；自动化全部采用合成语料、隔离 SQLite 和 fake/mock providers。

文件名是建议，实施前再核对职责和现有结构；无需本次先创建空壳。现有 `LLMProvider` 接口保持不变。

## 8. 风险与下一步门槛

1. **来源新鲜度没有现成的索引契约。** Parsing report fingerprint 绑定文件，Knowledge fingerprint 还绑定 chunks，但 DocumentChunk 本身没有 parser/content 版本。不能凭“表里有 chunk”就索引。应记录 source + chunk set + preparation/model 版本，旧数据状态不明则报告而非猜测。
2. **Chunk 替换与 ID。** `replace_chunks` 先删除再插入；ID 可能变化或被 SQLite 重用。未来外键需明确级联/失效策略，不能仅按 ID 命中旧向量，更不能阻塞原有解析事务。
3. **解析失败可能保留旧文本。** 文件更新失败、重解析失败、旧警告/源文件缺失均需从可检索集合中排除。另一方面，AI generation 失败不一定代表原文无效；索引资格应依据文本/源版本而非要求 knowledge completed。
4. **质量覆盖不足。** 部分 resources 没有报告，少量 chunks 极短；公式、图表、扫描页的文本存在固有限制。保持原页链接，不承诺多模态理解；报告“未知”不等于警告不存在。
5. **过滤会影响召回。** 历史 `other` 多、classification holdout 仍 pending；不能把 regression 100% 当作 unseen 分类准确率，更不能默默丢弃 other。首次发现的共享文件目前只有一个所属 Week，也限制按 Week 过滤时的覆盖。
6. **重叠与 token 预算。** 默认按字符分块，overlap 会导致相邻重复命中；需要有界去重和上下文预算，真实 embedding 长度限制选型后验证。
7. **现有 grounding 不是通用 RAG validator。** 它约束单 Resource 和知识抽取 schema；课程问答需要跨资源但不跨课程的 citation map。引用存在不能证明句子正确，必须测试不支持推论与拒答。
8. **模型与成本。** Chat provider 不等于 embedding provider；模型切换必须使旧索引失效。问答不能触发整份资料提取，不能持有 DB 写锁等待模型；不默认加入额外无限审查调用。
9. **隐私与运行限制。** 本地材料、向量与问答日志仍可能含私有信息，沿用忽略规则；不发送超出当前检索范围的整份课程内容。现有同步为单 worker，不借 RAG 引入并发写入复杂度或后台自动收费任务。

本次只新增这份文档，保留已有未提交的 Holdout Eval 改动；未修改生产代码、classifier、Gold 或 Holdout 数据。执行了源码核查、SQLite 只读结构/汇总查询和文档检查；未启动应用、未调用 Canvas/LLM、未解析 PDF、未生成 embedding，也未运行完整项目验收。
