# Phase 4：PDF 解析与切块

DocumentService 只处理本地 PDF，不访问 Canvas、数据库或 AI。API 调用 document_processing 编排服务，后者通过 repository 将结果存入已有 DocumentChunk 表。无需数据库迁移。

## 数据流与文件

```text
Resource.local_path → MATERIALS_ROOT 内的 PDF
→ DocumentService / PyMuPDF → ParsedDocument / ParsedPage
→ clean_text → 每页独立 split_page → DocumentChunkCreate
→ document_processing → document_chunks repository → SQLite
```

- `app/services/document_service.py`：路径/文件验证、提取页面、元数据和空页统计、生成 chunks。
- `app/services/document_chunking.py`：轻量清洗和纯文本切块。
- `app/services/document_processing.py`：单资源处理、事务及状态更新。
- `app/services/document_errors.py`：对外安全的业务错误。
- `app/schemas/document.py`：ParsedPage、ParsedDocument、ParseSummary。
- `app/repositories/document_chunks.py`：限定资源的替换及分页读取。
- `app/api/documents.py`：两个开发 API。
- `tests/test_documents.py`：临时 PDF、隔离内存数据库及 API 测试。

## 解析规则

依赖 PyMuPDF，使用 `import pymupdf` 和 `page.get_text("text", sort=True)`。按页提取一次，页码从 1 开始；保留 title/author 等 PDF 字符串元数据。配置的 materials 根目录限制解析范围，拒绝越界路径、非 PDF、空文件、缺失文件及加密 PDF；捕获损坏或不可读文件错误。PyMuPDF 调用在进程内串行执行，避免线程并发调用该库。

清洗统一 CRLF/CR 换行，删除 NUL、行末空白，将三个以上换行压缩成两个。保留行首缩进、行内空格、短标题、公式、代码、Unicode 和 bullets。Phase 4.1 保留 raw_text 和 span 元数据；仅在位置、字号和跨页重复率均满足保守条件时，移除清洗文本中的重复页眉页脚。详见 [公开质量改进规则](validation-summary.md)。

`sort=True` 尽量改善阅读顺序，不能恢复所有版式。公式上下标、表格、图表、复杂多栏仍可能退化为平面文本。详见 [PyMuPDF 官方文本提取说明](https://pymupdf.readthedocs.io/en/latest/app1.html)。

质量摘要增加 pages_with_warnings、pages_with_formula_warnings、pages_with_encoding_warnings、repeated_headers_removed、repeated_footers_removed 和 page_warnings。公式结构风险仅标记、不重建；status=parsed 不代表公式无损。

## Chunk 配置

```dotenv
DOCUMENT_CHUNK_SIZE=2000
DOCUMENT_CHUNK_OVERLAP=200
```

单位是 Python 字符数，不是 token。size 范围 100–20000；overlap 必须非负且小于 size。实际块长度不超过 size，但短页面仍生成短块。优先在窗口后半段寻找段落、换行、句末、单词边界，找不到才硬切；后半段限制避免反复生成过小的块。下一块最多回退 overlap 个字符，并尽可能向前移至完整单词边界，因此实际重叠可能较少。没有可用分隔符时按字符硬切。

**Chunk 不跨页**。空白页面不生成 chunk。每个 Resource 的 chunk_index 全局从 0 递增；page_number 保留原始物理 PDF 页号。数据库既有 UNIQUE(resource_id, chunk_index) 继续有效。Create/Read schema 不裁剪 content，确保代码缩进和原文切片往返不变。

## 状态、重复处理与事务

先完成解析及切块，再仅删除当前资源旧 chunks、插入新 chunks，并在同一事务更新 Resource 为 parsed。重复调用替换旧数据，数量不会累积。其他 Resource 的数据保持不变。

解析失败：标记 failed，保留已有 chunks。数据库失败：rollback，保留原 chunks 和先前 Resource 状态，不提交半成品。API 不返回底层 SQL 或文件内容。暂不新增 parsing 枚举值。

空白或图片页返回空 text、has_text=false，并纳入统计。当含文本页比例 <=10% 时标记 possible_scanned_pdf=true；API 返回 status=needs_ocr、chunks_created=0，Resource 标记 failed，保留旧 chunks。这是空页比例启发式，不能准确判断所有扫描 PDF，尤其是带少量页眉文字的扫描文件。部分无文本页会给出 warning。没有 OCR、Vision Model 或图像理解。

## API

后端运行后，用已下载且 local_path 已保存的真实 Resource ID：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/resources/3/parse
Invoke-RestMethod 'http://127.0.0.1:8000/api/resources/3/chunks?offset=0&limit=100'
```

- `POST /api/resources/{resource_id}/parse`：返回 resource_id、filename、total_pages、pages_with_text、empty_pages、total_characters、chunks_created、possible_scanned_pdf、status、warnings。
- `GET /api/resources/{resource_id}/chunks`：返回 id、resource_id、page_number、chunk_index、content、created_at，按 chunk_index 排序。offset 默认 0，limit 默认 100、最大 200。
- 不存在的资源 404；无 local_path、不支持或损坏的 PDF 422；数据库错误 500。
- 扫描疑似文件 HTTP 200 表示检测完成，必须检查业务 status=needs_ocr，不能将 HTTP 200 当作解析成功。

这些是本地开发 API，无认证，仅在 localhost 运行。尚无任务队列、自动解析、批量同步或缓存跳过；重新调用 parse 会明确重新解析。

## 测试

在 backend 执行 `.venv\Scripts\python.exe -m pytest -q`。普通测试使用动态生成的临时 PDF、SQLite 内存数据库、Mock Canvas；无需真实材料或 Token。不含私人课程内容的结果见 [公开验证摘要](validation-summary.md)。

当前阶段完成后停止。下一阶段才实现 AIService、结构化知识输出与 schema validation。
