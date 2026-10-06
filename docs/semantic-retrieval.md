# RAG V0 — Local Semantic Retrieval Prototype

本阶段只返回 Top-K 原文 chunks，不生成答案，不添加 API 或 UI。复用已有 DocumentChunk，严格先按 Course 筛选，默认包含 lecture/tutorial/other。

## 安装与准备

在 `backend` 目录、现有 Python 环境中执行：

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-retrieval.txt
.venv\Scripts\python.exe -m evals.rag_retrieval prepare-model
```

`requirements-retrieval.txt` 是独立可选依赖，不改变 V1 启动依赖。模型为 `BAAI/bge-small-en-v1.5`，通过 FastEmbed 0.8.1 / ONNX Runtime 在 CPU 本地推理，384 维。仅 `prepare-model` 允许下载公开模型；索引和查询只读取本地 cache，无远程推理、付费 API 或凭据需求。Cache 默认在 Git 忽略的 `data/embedding-models/`，可用 `--model-cache` 指定本地路径。

参考：[FastEmbed](https://qdrant.github.io/fastembed/)、[query_embed / passage_embed](https://github.com/qdrant/fastembed/blob/main/fastembed/text/text_embedding.py)。这里只使用本地 embedding 库，不使用 Qdrant 服务或任何独立向量数据库。

本地模型主要面向英语；跨语言、公式、代码检索质量尚未由人工 Gold 验证。长文本通过临时 token windows 做加权平均后归一化，不静默丢弃尾部；仍然每个已有 chunk 对应一个向量，不新建/替换 DocumentChunks，不重新解析 PDF。

## 运行（一次明确选择一个课程）

将 `COURSE_ID` 替换为本地数据库中已有的 Course.id：

```powershell
.venv\Scripts\python.exe -m evals.rag_retrieval stats --course-id COURSE_ID
.venv\Scripts\python.exe -m evals.rag_retrieval index --course-id COURSE_ID
.venv\Scripts\python.exe -m evals.rag_retrieval search --course-id COURSE_ID --query "What is CRC?" --top-k 5
```

可选过滤：在 search 后添加 `--resource-type lecture`；Lecture + Tutorial 则重复参数 `--resource-type lecture --resource-type tutorial`。不传即包含所有类型。不自动重分类、不自动扩展到其他课程，也不因查询而创建 embedding。

搜索输出包括 chunk_id、cosine score、完整 chunk text、Resource.id/filename、Course.id/code/name、Week.id/title、PDF 页码、resource_type、相对 source link 和已存储解析警告。链接例如 `/api/resources/RESOURCE_ID/file#page=PAGE`，可接在正在运行的前端/后端地址后打开。没有 registered local_path 时链接为 null；是否文件仍存在由现有文件 endpoint 决定。分数只是相似度，不是正确率/置信度。

## SQLite 索引与失效

新增 `chunk_embeddings` 表，保存：

- chunk_id（主键，外键 ON DELETE CASCADE）；
- embedding 数组（JSON）及 dimensions；
- model、model_version（模型文件、运行库与输入处理策略的哈希）；
- content_hash、source_hash；
- generated_at（UTC）。

不重复存储正文。每个 chunk 只保存一个当前模型向量；换模型/版本后检索不会混用不同空间，显式 index 才替换向量。索引前检查已存向量，未变且有效则跳过；内容、页码/资源归属、源 revision、路径或解析报告变化会使向量失效。分类仅通过实时 join 过滤，resource_type 变化不会重新 embedding。

index 只创建新索引表，不运行应用 startup/recovery 或整个 schema upgrade。已有应用正常初始化也会注册这张新表。原文数据和业务表不重建。现有 chunk replacement 删除旧 chunks 时由外键自动清理向量，不改变 chunk pipeline。每批推理在数据库写事务外进行，写入前加锁复核来源；失败回滚该批，先前成功批次可在下次跳过。

检索只使用所选课程中内容/源哈希、模型/版本、维度一致的有效向量。缺失、过期、损坏或零向量跳过，无向量时不调用 query embedding。相同分数按 chunk_id 排序。Top-K 默认 5，范围 1–100。

## 独立 Retrieval Eval

真实问题放在 Git 忽略的 `data/retrieval-eval/questions.json`；公开空模板为 `backend/evals/retrieval_questions.example.json`。手工添加：

```json
[
  {
    "question": "A manually written question about this course",
    "course_id": 123,
    "expected_resource_id": 456,
    "expected_pages": [2, 3]
  }
]
```

示例 ID 和页码是占位值，需要替换为已有 Course.id、属于它的 Resource.id 和实际 DocumentChunk.page_number（PDF 从 1 开始的页码）。先根据已存原文独立标注预期来源/证据页，再看模型结果；不要从排名反推标签。多个页面只要实质支持问题中的一部分即可记录，排除封面、大纲、仅标题页及仅提到关键词的页面。一次 eval 只接受指定课程的问题；未存在、跨课程的资源或该资源没有 chunk 的证据页会报错。不重新解析 PDF。

```powershell
.venv\Scripts\python.exe -m evals.rag_retrieval eval --course-id COURSE_ID --dataset ../data/retrieval-eval/questions.json
```

输出两组独立指标：

- Resource Hit@1/3/5：前 K 个 **chunk** 中至少一个来自 expected_resource_id，保留 V0 定义；同一资源的多个 chunks 不压缩成一个名次。
- Evidence Hit@1/3/5：同一个 chunk 必须同时命中 expected_resource_id 和 expected_pages 中的页码。

`expected_pages` 可省略、为 null 或空数组，表示证据标注 unresolved：仍计入 Resource 指标，但不进入 Evidence 分母。非空值只能是无重复的正整数数组。输出 resolved/unresolved 数量；空集或没有已标注证据时显示 N/A，不代表 0% 或 100%。Evidence Hit@5 失败时打印问题、预期资源/页面以及 Top-5 的 rank、score、resource id/title、page、chunk id 和最多 300 字符的原文预览。预览仅截短，不重写正文。

命中任意一个有效证据页不代表已覆盖复合问题的全部答案，也不保证该页的公式提取无误。单一 expected_resource_id 仍是当前限制，其他合理来源不会计为命中。每次 CLI eval 直接调用生产 RetrievalService，不混入 Classification Regression/Holdout。

### 冻结 Baseline

V0 Resource Baseline 保留为 8/10、9/10、10/10（Hit@1/3/5）。原始结果 `data/retrieval-eval/rag-v0-baseline-first.json` 不覆盖；旧 Gold 精确备份为 `questions.v0-resource.json`。V0.1 在独立审查并冻结证据页后，对 **同一组已保存的 V0 Top-5** 重新评分，单独保存 `rag-v0.1-evidence-baseline.json` 和 `.md`。这是评估标准的变化，不是重新检索或优化后的结果，不需要再次计算 query embedding。

V0.1 首次证据重评分：10 条已标注，0 条 unresolved；Evidence Hit@1/3/5 = 3/10（30%）、8/10（80%）、9/10（90%）。Resource 指标不变。这是当前 10 题的结果，不代表 unseen accuracy，也不代表完整回答覆盖率。

真实证据标注、哈希记录、报告和文本预览均保存在 Git 忽略的 `data/retrieval-eval/`。公开文档不包含私人课件内容。之后主动运行上述 CLI 会执行一次新的本地查询；请另存结果，不覆盖任何冻结 Baseline。

## 边界与检查

### V0.2 Retrieval Hygiene

只在检索候选选择阶段调用 `retrieval_hygiene.low_information_reason`，排除两种明确模板；不修改索引生成、DocumentChunk 原文、模型、余弦计算或 Top-K 排序：

- 封面：4–12 个非空短行、总计不超过 60 个空格分隔词、每行不超过 10 词，同时包含开头的课程编号/名称、Week/Lecture/Session 编号标题、School/Department/Faculty 院系行。
- 目录：明确的 Syllabus/Outline/Table of Contents 标题，最多 200 词，之后至少 3 个带列表标记的短主题，每项不超过 10 词。支持提取后并排的编号列。

出现疑似正文谓词、提问、URL 或计算符号时保守保留。规则不使用 page_number、资源 ID、查询或 Gold，不把“很短”“位于第一页”本身视为过滤依据。短定义、公式、缩写展开、普通短标题、图示文字以及不符合模板的页面保留。它是有限的英文模板启发式，不是通用页面类型判断；可能漏掉其他封面，也不能保证理解所有无标点短句。

调试时可给现有生产搜索传入列表：

```python
diagnostics = []
hits = service.search(db, course_id, query, top_k=5, diagnostics=diagnostics)
# diagnostics: chunk_id, resource_id, page_number, low_information_reason
```

仅记录原本索引有效且满足课程/类型过滤、随后被 hygiene 排除的候选。不输出原文到日志，不增加正常 RetrievalHit 字段。规则不在 index_course 中执行；已有向量保留，也不需重新 embedding。

本次对冻结的 10 题进行一次新的本地检索，模型/version 和 Gold 完全不变。结果单独保存在 Git 忽略的 `data/retrieval-eval/rag-v0.2-hygiene-baseline.json` / `.md`，包括每题六项指标前后对比与排除原因：

| 指标 | V0/V0.1 | V0.2 |
|---|---|---|
| Resource Hit@1 | 8/10 | 9/10 |
| Resource Hit@3 | 9/10 | 9/10 |
| Resource Hit@5 | 10/10 | 9/10 |
| Evidence Hit@1 | 3/10 | 4/10 |
| Evidence Hit@3 | 8/10 | 8/10 |
| Evidence Hit@5 | 9/10 | 9/10 |

检测并排除了 629 个候选中的 11 个（9 个封面、2 个目录），没有 Gold 证据页被排除。唯一退化是 Q02 Resource Hit@5：原先命中的大纲被排除，正确正文仍未进入 Top-5；该题的 Evidence Hit@5 前后均失败。其余问题的六项指标没有退化。此结果未解决 Q02，不据此追加规则，也不代表 unseen accuracy。

- 本 prototype 检查数据库中已存 chunk/source 状态，不打开 PDF。下载/解析未完成或失败而遗留的旧 chunks 不参与索引；仅 knowledge 阶段失败、原文仍已解析的资源可使用。
- 解析警告来自已存报告；未在查询时重新验证 PDF 文件 fingerprint，报告 freshness 不保证。报告缺失显示 unknown，绝不默认为已验证安全。文件被数据库之外的操作静默替换仍是限制；因此本阶段仅返回原文，不能直接升级成可信 RAG 回答。
- 检索检查 query inference 前后源 metadata/content 是否改变。新模型、文本缺失、异常输入、无匹配均不回退至生成 API。
- 自动化使用隔离 SQLite、合成文本和 fake embedding，覆盖课程隔离、排序、过滤、来源、增量失效、外键级联、并发源变化、异常向量和 Eval 指标。
- 私有材料、数据库、模型 cache、真实查询结果和备份保留在忽略的 data/materials 目录；不要把 CLI 的课程正文输出提交到 Git。
- 不加入答案生成、query API、前端、Agent、MCP、Memory、Hybrid Search、reranker 或 query rewriting。
