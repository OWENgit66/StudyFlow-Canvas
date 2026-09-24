# StudyFlow

面向大学生的个人课程学习平台，目标是按 Semester → Course → Week 整理课程资料并生成有来源的结构化学习知识。

**V1 MVP：Complete / Stable。V2.1：Resource Classification。** 已完成 Canvas → 本地 PDF → 分页解析 → AI 结构化知识 → SQLite → 学习网页的完整流程，并通过真实单文件验收和自动化回归。V2.1 增加 lecture / tutorial / other 资源类型及 Week 页面标签；V2.2 尚未开始。发布状态见 [V1 验证记录](docs/v1-release.md)，后续计划见 [Roadmap](docs/roadmap.md)。

## V1 功能

- 单用户本地平台，按 Semester → Course → Week → Resource 组织资料。
- Canvas REST API 只读集成，支持分页、受控下载和手动 Sync Canvas。
- Module 中的 Page 可通过官方 API 读取 HTML，发现课件链接并复用现有 Resource 流程；Canvas 文件按 ID 去重，安全的外部直链 PDF 使用独立身份。详见 [Page-linked materials](docs/page-materials.md)。
- 默认跳过明确标为 Reading / Reference 的资料，不下载、不解析、不调用 AI；Lecture / Tutorial 等核心教学资料正常处理，无法判断的资料保留原流程并报告 UNKNOWN。直接 File 与 Page 链接共用可配置分类规则。
- 以数据库中的 active Semester 和 Canvas term ID 为唯一同步范围；历史课程保留，但不进入默认 Dashboard 或同步发现流程。
- 同步以后台请求启动，通过轮询显示课程、Module、文件、阶段和真实计数；支持安全取消及中断状态恢复。
- 基于 Canvas file ID 与更新时间增量同步；unchanged 文件跳过下载、解析与 AI，记录状态、计数和每文件失败。
- PyMuPDF 按页提取、清洗与切块，保留来源页；检测公式布局、异常编码及重复页眉页脚风险，不猜测修复公式。
- Original materials 显示 PDF 解析健康状态、需复核页数及逐页问题说明，支持直接打开对应 PDF 页；课程/Module 汇总需复核资料数量。
- 可替换的 LLMProvider：OpenAI 和 DeepSeek；分批生成结构化 JSON，执行 Pydantic、来源、符号安全和语义支持检查后事务保存。
- Dashboard、Course、Week 页面展示概览、概念、要点、可靠公式、例子、练习问题及有材料支持的考试提示；空的可选栏目不显示。
- 答案本地展开/收起、来源 PDF 页链接、安全原件打开/下载；默认隐藏 stale 知识，支持桌面与窄屏布局。

## V1 架构

```text
Next.js / TypeScript / Tailwind
             │ same-origin /api proxy
             ▼
FastAPI API → SyncService → CanvasService (GET only)
                  │                  │
                  │              materials/ PDF
                  ▼                  ▼
             DocumentService → page chunks + quality warnings
                  │
                  ▼
             KnowledgeService → AIService → LLMProvider
                  │                        ├─ OpenAI
                  │                        └─ DeepSeek
                  ▼
       Schema / provenance / symbolic / semantic validation
                  │
                  ▼
       Repositories → SQLAlchemy → SQLite
                  │
                  └─ current knowledge → learning pages
```

数据库主关系为 Semester → Course → Week → Resource → DocumentChunk；ResourceKnowledge 保存资源级结构化结果与版本指纹，并更新 Summary、Concept、Question 投影。SyncRecord 保存同步结果。原件位于本地 materials，数据库与调试结果位于 data；两者均不提交 Git。

## 开发规则

根目录 [AGENTS.md](AGENTS.md) 是项目的长期开发规则。每个阶段先检查仓库，再实现、运行、验证和修复。V1 保持稳定；V2 按阶段扩展。资源类型、兼容迁移及分类边界见 [V2.1 Resource Classification](docs/resource-classification.md)。

## 技术栈与结构

- Frontend：Next.js App Router、TypeScript、Tailwind CSS、ESLint。
- Backend：Python、FastAPI、Uvicorn、Pydantic / pydantic-settings。
- Canvas HTTP：沿用现有 httpx2 客户端（测试和运行共用一个 HTTP 库）。
- 两个独立本地进程；前端通过同源 `/api` proxy 调用 FastAPI，不向浏览器传递 Canvas / LLM 凭据。
- Database：SQLite + SQLAlchemy 2，同步 Session 按请求创建和关闭。
- PDF：PyMuPDF，按页提取、轻量清洗、可配置字符切块和来源追踪。

```text
StudyFlow/
├── AGENTS.md
├── .gitignore
├── .env.example
├── README.md
├── frontend/
│   ├── src/app/
│   │   ├── page.tsx            # 学期 / 课程 Dashboard
│   │   ├── courses/[id]/       # Course 页面
│   │   ├── weeks/[id]/         # Module 学习页面
│   │   ├── layout.tsx          # 根布局与页面元信息
│   │   ├── globals.css         # Tailwind 入口
│   │   └── favicon.ico
│   ├── src/components/        # 课程、知识、来源、资料、同步与状态组件
│   ├── src/lib/               # API client、真实响应类型与读取 hook
│   ├── tests/                 # 独立 mock fixtures / UI 交互测试
│   ├── .env.example           # 仅前端 API 地址配置，无服务端凭据
│   ├── public/                # 静态资源
│   ├── package.json
│   ├── package-lock.json      # 前端依赖锁定
│   ├── tsconfig.json
│   ├── next.config.ts
│   ├── postcss.config.mjs
│   ├── eslint.config.mjs
│   ├── .gitignore
│   ├── AGENTS.md              # Next.js 工具生成的框架规则
│   ├── CLAUDE.md              # 工具生成，引用同目录规则
│   └── README.md
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py            # FastAPI 入口
│   │   ├── init_db.py         # 显式建表命令
│   │   ├── seed.py            # 独立、可重复的开发数据脚本
│   │   ├── check_canvas.py    # 显式只读真实连接检查
│   │   ├── api/               # health、catalog、canvas、documents、knowledge、sync、study
│   │   ├── core/              # config.py、database.py
│   │   ├── models/            # 9 个基础实体 + resource_knowledge + common.py
│   │   ├── schemas/           # 数据库、Canvas、ParsedPage/ParsedDocument schemas
│   │   ├── services/          # Canvas、Document、Knowledge、AI、Sync 与 providers
│   │   └── repositories/      # catalog、document_chunks、knowledge、sync
│   ├── tests/                 # database、API、schemas、Canvas mock、PDF 测试
│   ├── pyproject.toml
│   ├── requirements.in       # 直接依赖
│   ├── requirements.txt      # 运行依赖固定版本
│   ├── requirements-dev.in
│   └── requirements-dev.txt  # 含运行依赖的测试环境固定版本
├── materials/                # 原始课程文件；按学期/课程/Module 整理，不入库
├── data/                     # studyflow.db、phase4-qa/；本地数据不入库
└── docs/
    ├── database.md
    ├── phase-1-verification.md
    ├── phase-2-verification.md
    ├── canvas.md
    ├── phase-3-verification.md
    ├── material-storage.md
    ├── documents.md
    ├── validation-summary.md
    ├── ai-knowledge.md
    ├── sync.md
    ├── interface.md
    ├── v1-release.md
    └── roadmap.md
```

读接口使用 API → Repository → SQLAlchemy 分层；写入和工作流由 Service 编排，CanvasService 只负责 HTTP 与文件下载，不直接访问数据库。配置与凭据留在后端。

## 环境要求

已验证环境：Windows PowerShell、Node.js 24.14.0、npm 11.9.0、Python 3.12.8。建议使用 Node.js 24 LTS 和 Python 3.12。首次安装依赖需要网络。

## Starting StudyFlow

Windows 完成下方依赖安装并在 `frontend` 执行一次 `npm run build` 后，双击：

- 启动：`launcher\StudyFlow.cmd`
- 停止：`launcher\Stop StudyFlow.cmd`

启动器自动定位项目，后台启动现有 FastAPI（8000）与 Next.js production（3000），等待后端健康检查及前端就绪，然后在默认浏览器打开 `http://localhost:3000`。重复点击会复用已运行服务；停止时只终止启动器记录并验证身份的进程树，手动启动的服务不受影响。

日志在 `logs/`，进程身份文件在 `.runtime/`，均由 Git 忽略。启动失败时窗口保留并显示原因或日志位置；启动器不安装依赖、不自动构建、不复制 `.env`、不触发 Canvas/AI。修改前端代码后请先停止服务并重新 `npm run build`。

桌面快捷方式：右键 `launcher\StudyFlow.cmd` → 显示更多选项 → 发送到 → 桌面快捷方式，将其重命名为 **StudyFlow**。可在快捷方式属性中更换图标；也可按 Windows 提供的选项固定到开始菜单或任务栏（不同版本可能不支持直接固定 `.cmd`）。项目移动后需更新快捷方式目标。完整命令、故障排查和验证见 [Windows launcher](docs/windows-launcher.md)。

## 手动安装与运行

在项目根目录打开两个终端。

### 后端

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

直接使用虚拟环境中的 Python，无需修改 PowerShell 激活脚本策略。

macOS / Linux 将 `.venv\Scripts\python.exe` 替换为 `.venv/bin/python`，创建环境使用 `python3 -m venv .venv`。

- 健康检查：http://127.0.0.1:8000/health
- API 文档：http://127.0.0.1:8000/docs
- OpenAPI：http://127.0.0.1:8000/openapi.json

### 前端

```powershell
cd frontend
npm ci
npm run dev -- --hostname 127.0.0.1
```

访问 http://127.0.0.1:3000。若 PowerShell 阻止 `npm.ps1`，使用 `npm.cmd` 执行同样命令。

前端需要同时运行后端。默认通过同源 `/api` proxy 连接 `http://127.0.0.1:8000`。可参考 `frontend/.env.example` 在 `frontend/.env.local` 配置 `NEXT_PUBLIC_API_BASE_URL`（默认留空）和 `BACKEND_API_URL`；修改后重新构建/启动。前端不加载根目录或 backend 的 Secrets，禁止将 Canvas/LLM key 放入前端。

生产构建与启动：

```powershell
npm run build
npm run start -- --hostname 127.0.0.1
```

开发服务与生产服务默认使用相同端口，先用 Ctrl+C 停止开发服务。首页使用系统字体，不依赖在线字体下载。

## 环境变量与 Secrets

应用通过 pydantic-settings 读取 `backend/.env` 和根目录 `.env`；优先级为系统环境变量 > 根目录文件 > backend 文件。可从 `.env.example` 创建自己的 `.env`（不要覆盖已有配置）。未设置时使用默认值：

```dotenv
DATABASE_URL=sqlite:///data/studyflow.db
```

相对路径始终相对于项目根目录解析，与启动命令的工作目录无关；不需要填写机器绝对路径。当前仅支持 SQLite URL。Canvas 与 LLM 配置已启用；未配置 LLM 不影响后端启动，知识生成会返回明确的 503。

不要把 Token、API Key 或密码提交到 Git，也不要将秘密放入 `NEXT_PUBLIC_*` 变量。忽略规则已覆盖本地环境文件、虚拟环境、依赖、构建产物和本地数据。`.env.example` 仅保留空凭据占位符；真实材料、解析与 AI 输出、详细课程验收记录均留在本地。提交前仍需检查暂存内容：Git ignore 不会保护已经跟踪的文件，也不能识别误写入源码的密钥。

## API

| Method | Path | Response |
| --- | --- | --- |
| GET | `/health` | HTTP 200，`{"status":"ok"}` |
| GET | `/api/semesters` | 学期列表 |
| GET | `/api/courses` | 当前 active 学期课程；`?semester_id=` 显式读取历史 |
| GET | `/api/courses/{course_id}` | 单门课程 |
| GET | `/api/courses/{course_id}/weeks` | 按 week_number 排序的周列表 |
| GET | `/api/weeks/{week_id}` | 单周详情 |
| POST | `/api/resources/{resource_id}/parse` | 解析、替换 chunks，返回统计及状态 |
| GET | `/api/resources/{resource_id}/chunks` | 按 chunk_index 分页读取 |
| POST | `/api/resources/{resource_id}/knowledge` | 调用配置的 LLM，验证并保存知识 |
| GET | `/api/resources/{resource_id}/knowledge` | 默认只返回当前知识；无当前结果时 404；`?include_stale=true` 显式读取历史 |
| POST | `/api/sync` | 仅 active 学期；`?background=true` 返回 202 和 id；`?dry_run=true` 只发现与分类，两参数可组合 |
| GET | `/api/sync/current` | 正在运行的同步或 null，页面刷新后恢复轮询 |
| GET | `/api/sync/{sync_id}` | 同步状态、计数、事件、错误和可用 usage |
| POST | `/api/sync/{sync_id}/cancel` | 请求协作式取消，当前外部请求可能需要先结束 |
| GET | `/api/study/dashboard` | 学期、课程统计、最新同步摘要；不返回内部错误/路径 |
| GET | `/api/weeks/{week_id}/resources` | Module 资料列表、可用性及大小；不返回 local_path |
| GET | `/api/resources/{resource_id}/file` | 安全打开注册资料；`?download=true` 下载；仅 PDF inline |

学期和课程列表支持 `offset`（默认 0）和 `limit`（默认 100，上限 100）。有效 ID 不存在返回 404，非法参数返回 422；存在但无周的课程返回空列表。响应为平坦对象，不展开所有关系。

`/health` 仅表示 API 进程可响应，不主动探测数据库或外部服务。

## Canvas 配置与验证

Canvas 配置、只读 API、下载调用与错误码见 [Canvas 集成说明](docs/canvas.md)。先在根目录 `.env` 设置 `CANVAS_BASE_URL`（仅 HTTPS 实例地址，不带 `/api/v1`）和 `CANVAS_ACCESS_TOKEN`，然后在 backend 执行：

```powershell
.venv\Scripts\python.exe -m app.check_canvas
```

程序只读取连接状态、课程、Modules、Items 和文件元数据；不下载、不写入 Canvas 或数据库。缺少凭据时明确报告未验证，不影响后端启动。也可访问 `GET /api/canvas/status`，未配置时返回 configured=false / connected=false。

可选设置：`CANVAS_TIMEOUT_SECONDS=20`、`CANVAS_MAX_PAGES=100`、`CANVAS_MAX_DOWNLOAD_BYTES=104857600`、`MATERIALS_ROOT=`（留空使用项目根目录 materials）。所有示例值已写入 `.env.example`，存储相对路径按项目根目录解析。

### 当前学期与同步进度

`Semester.is_active` 指定当前学期，SQLite 唯一约束保证最多一个 active 行；`Semester.canvas_term_id` 对应 Canvas `enrollment_term_id`。CanvasService 请求 `include[]=term`，只接受匹配且可访问的课程，再请求 Modules / Items / Files。缺少映射或冲突时不猜测名称/日期、不放宽范围。历史记录保留，默认 Dashboard 和 courses API 只读取 active 学期。

在 backend 中可显式配置一个**已存在**的 Semester（替换为本地与 Canvas 的真实 ID；无同步运行时执行）：

```powershell
.venv\Scripts\python.exe -m app.configure_semester --semester-id <local-id> --canvas-term-id <canvas-term-id>
```

配置命令不触发同步，也不重新分配历史课程。`SYNC_SEMESTER_ID` 是旧配置兼容项，应留空；若设置为不同于 active 行的 ID，同步会拒绝执行。首次安装未配置 active 学期时默认列表为空，同步返回明确错误。

网页以 `POST /api/sync?background=true` 启动，按约 1 秒间隔串行读取状态。先发现当前学期范围内的唯一文件，再逐个处理；发现期间显示不确定进度，完整发现后按 `(完成 + 跳过 + 失败) / 总文件数` 展示进度条、百分比及剩余数量。当前处理文件不算完成；发现部分失败时明确提示总范围不完整。

进度栏显示课程、Module、文件、当前操作，以及后端确认的发现/下载/解析/生成/审查/保存步骤状态；生成阶段显示真实批次。显示已用时间和最后进度更新时间，不估算剩余时间，不以轮询刷新冒充后端心跳。失败文件可展开查看安全的文件名与阶段，其他文件继续处理。用户可继续浏览课程、周页面与已有知识；窄屏堆叠显示身份信息和两列计数。

Cancel Sync 在下一安全边界停止；当前外部调用可能需要等到返回或超时，完成资料与可恢复阶段保留。终态停止轮询并收起为结果摘要；取消结果显示尚未处理数量。启动时将遗留 running 记录标记 cancelled，绝不自动重启付费工作。

仍只支持一个后端 worker、一个进程内任务，无任务队列或调度器。操作细节、迁移及本次验证见 [当前学期同步](docs/active-semester-sync.md)。

## 原始课程资料

Canvas 原始 PDF / PPTX / DOCX 等文件默认保存在项目根目录：

```text
materials/<year>-<term>/<Course Code> - <Course Name>/<Canvas Module Name>/<filename>
```

MATERIALS_ROOT 可选，留空即使用默认目录。保留正常原始文件名，重名追加 (2) 等后缀；Resource.local_path 优先保存相对项目根目录的路径。临时文件在 materials 外，数据库和解析数据不放入该目录。

目录规则、调用方式和测试记录见 [资料存储说明](docs/material-storage.md)。下载的私有课件及其截图、完整提取文本和本地验证产物不包含在源码仓库中。

## PDF 解析与切块

读取 Resource.local_path 对应的 materials PDF，使用 PyMuPDF 按页提取。默认 `DOCUMENT_CHUNK_SIZE=2000`、`DOCUMENT_CHUNK_OVERLAP=200`（字符），优先自然边界、chunk 不跨页，保留从 1 开始的来源页号。先完成解析，再事务替换当前资源 chunks；失败回滚。扫描疑似文件返回 needs_ocr，暂不 OCR。

现已保留 raw_text/cleaned_text 和 span 元数据，提供逐页质量警告与保守重复页脚清理，不重建公式。规则与真实结果见 [公开解析质量说明](docs/validation-summary.md)。

功能、API 示例和限制见 [PDF 解析说明](docs/documents.md)；不含私人课程内容的验证摘要见 [公开验证记录](docs/validation-summary.md)。

解析健康报告保存在 Resource 的紧凑 JSON 中，并绑定实际 PDF 内容指纹。文件变化后旧警告不作为当前报告显示；缺少报告也不会误显示健康。正常读接口只读取/验证报告，不重新解析或调用 AI。已有当前学期资料可用 `python -m app.refresh_parsing_health` 显式补充报告，不替换 chunks 或知识。逐页复核操作、维护方式及测试结果见 [Document Parsing Health](docs/parsing-health.md)。

## AI 知识提取

在本地 `.env` 中选择 `LLM_PROVIDER=openai`（使用 `OPENAI_API_KEY`）或 `LLM_PROVIDER=deepseek`（使用 `DEEPSEEK_API_KEY`）。模型由 `LLM_MODEL` 原样指定，例如 DeepSeek 使用 `deepseek-flash`；不自动替换。OpenAI 使用 Responses structured output，DeepSeek 使用 Chat Completions JSON Output，两者都执行本地 schema 和来源校验。`KNOWLEDGE_OUTPUT_LANGUAGE` 可选，控制解释文字语言，原文证据与公式保持不变。显式调用 POST knowledge 会发送课程文本到 provider，可能产生费用。

默认输入按 12000 字符分批、最多 20 批；携带数据库 chunk ID、来源页和 parsing warnings，不发送 span metadata。应用校验 chunk 归属及页号，证据取自实际存储内容；不要求模型逐字复制引文。无考试提示的 exam-focus 条目被过滤并计数，公式保护覆盖公式数组及明显的数学表达式重建。引用与安全检查后，独立的语义支持阶段仅用实际引用 chunks 批量审查，删除不受支持的条目或解释；判定不是事实正确性的证明。结果原子写入 resource_knowledge JSON 表及既有 Summary/Concept/Question。完整说明、限制和验证见 [AI Knowledge](docs/ai-knowledge.md)。

## 数据库初始化与开发数据

FastAPI 启动时创建数据目录和缺失的表，不自动加入示例数据。也可在 backend 目录显式执行：

```powershell
.venv\Scripts\python.exe -m app.init_db
# 可选：加入 1 个学期、1 门课程、2 个周、1 条资源元数据
.venv\Scripts\python.exe -m app.seed
```

seed 可重复执行；不下载文件、不分配真实 Canvas ID，也不覆盖已有内容。正式启动不依赖 seed，克隆源码不会获得个人数据库或课件。

模型字段、关系、唯一约束与时间约定见 [数据库设计](docs/database.md)。`create_all()` 创建缺失表；V1 还包含已测试的同步字段增量升级。它不是通用迁移框架，未来更改 schema 仍需明确迁移方案与备份。

## 验证

```powershell
# 在 backend 中执行
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pip check
Invoke-RestMethod http://127.0.0.1:8000/health

# 在 frontend 中执行
npm test
npm run lint
npm run typecheck
npm run build
```

测试使用每例独立的 SQLite 内存数据库；磁盘持久化测试使用 pytest 临时目录，不访问开发数据库。配置、约束、ORM 关系、9 组 schemas 和 HTTP API 都有覆盖。

实际记录见各阶段 docs 报告及 [Phase 7 验证](docs/interface.md)。Phase 7 backend tests 为 458 passed、1 skipped（Windows 不允许创建符号链接），frontend 为 20 passed。Canvas/LLM 自动化测试不使用真实凭据，下载和 PDF fixtures 使用临时目录，不依赖个人课件。测试客户端使用当前 Starlette 要求的 httpx2；只有其已知 AnyIO 别名弃用提示被精确过滤，其他警告仍作为错误。

## Screenshots

真实 Dashboard、Week、移动布局和 PDF 来源截图已在本地验收。为避免提交私人课程信息，`docs/screenshots/` 保留在本地并由 Git 忽略；源码发布不附带这些图片。可使用独立合成数据预览（见 [界面验证说明](docs/interface.md)）检查页面。

## 当前验收状态

一份 41 页 / 41 chunks 的真实课件已完成 current knowledge 生成、页面浏览、来源、答案交互和 unchanged 同步验收；旧 stale 结果保留在本地快照中。完整私有验收记录与截图留在本地，源码中的 [V1 验证记录](docs/v1-release.md) 仅包含汇总结果。

## 范围与路线图

**V1：Complete。V2：Not started。** [Roadmap](docs/roadmap.md) 记录已交付范围和未启动的候选方向。当前没有 RAG、Embedding、向量数据库、用户认证、OCR、PPTX/DOCX 解析、后台任务队列或云部署。

V1 面向可信本机单用户运行，默认绑定 127.0.0.1；未设计为公开网络服务。复杂排版、扫描 PDF 和数学公式仍有提取限制，语义审查不是事实正确性的证明；需要时应通过来源链接核对原文。同步使用单 worker 进程内后台工作与 HTTP 轮询；取消不会强制杀进程。后续功能需要新的开发指令。
