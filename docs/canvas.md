# Phase 3 — Canvas 只读集成

本阶段提供读取、下载和 metadata 标准化，不执行数据库同步、Week mapping、文档解析或 AI。

## 配置

配置优先级：系统环境变量 > 根目录 `.env` > `backend/.env`：

```dotenv
CANVAS_BASE_URL=https://your-school.instructure.com
CANVAS_ACCESS_TOKEN=
CANVAS_TIMEOUT_SECONDS=20
CANVAS_MAX_PAGES=100
CANVAS_MAX_DOWNLOAD_BYTES=104857600
MATERIALS_ROOT=
```

BASE_URL 是实例 origin，不要填写 `/api/v1`、查询参数或嵌入用户名密码；必须 HTTPS。Token 由用户在本地配置，读取权限取决于账户与学校设置。不要提交 `.env`。

缺少凭据不会阻止 FastAPI 或数据库功能启动。只有调用 Canvas 功能时才创建客户端并检查配置。Token 使用 SecretStr，错误信息与本项目日志不输出 Token、上游响应 body 或下载链接。

## 文件与职责

| 文件 | 职责 |
| --- | --- |
| app/services/canvas_service.py | CanvasService，HTTP、认证、分页、读取和下载协调 |
| app/services/canvas_errors.py | 少量自定义、安全的异常 |
| app/services/canvas_storage.py | 文件名净化、流式落盘、禁止覆盖、失败清理 |
| app/services/canvas_mapping.py | CanvasCourse → CourseCreate，无数据库操作 |
| app/schemas/canvas.py | CanvasCourse、CanvasModule、CanvasModuleItem、CanvasFile、CanvasStatus |
| app/api/canvas.py | 服务注入、只读开发 API、异常响应 |
| app/check_canvas.py | 显式真实环境只读检查 |

HTTP 使用项目现有 httpx2（兼容 httpx 风格接口），从测试依赖提升到运行依赖；不额外引入 requests 或另一套 httpx。

## 服务接口

- `check_connection()`：读取 `/api/v1/users/self/profile`，仅检查身份请求成功，不返回个人信息。
- `get_courses()`：读取当前用户课程，保留 ID、name、course_code、workflow_state、start_at、end_at，不擅自过滤历史课程。
- `get_modules(course_id)`：保留原始 module name、position、workflow_state，不猜测周编号。
- `get_module_items(course_id, module_id)`：保留 type、title、content_id；File 类型暴露 canvas_file_id。其他类型（包括未知类型）正常返回。
- `get_files(course_id)`：读取课程文件列表。
- `get_page(course_id, page_url_or_id)`：通过官方 API 读取 Page HTML；Page 课件发现、去重和外部 PDF 安全限制见 [Page-linked materials](page-materials.md)。
- `get_file(file_id)`：读取独立文件 metadata，规范化 `content-type` 与 `url` 为 content_type、download_url。
- `download_file(file_id, context=...)`：重新获取 metadata，再下载，返回保存文件的 Path。

File item 一般只有 `content_id`。调用 `get_file(item.canvas_file_id)` 才取得 filename、content_type、size、updated_at、下载链接等完整信息。没有可用 content_id 时返回 None，调用方可跳过。受限制课程可能只有 ID；schema 接受这种情况，mapping 拒绝缺少课程名称/代码的数据，不凭空补造。

## 开发 API

全部为 GET，路径参数是 **Canvas ID**，与数据库 `/api/courses/{course_id}` 的本地 ID 不同。

| Path | 内容 |
| --- | --- |
| /api/canvas/status | 配置状态与实际连接检查 |
| /api/canvas/courses | Canvas courses |
| /api/canvas/courses/{course_id}/modules | Modules |
| /api/canvas/courses/{course_id}/modules/{module_id}/items | Module items |
| /api/canvas/courses/{course_id}/files | Course files metadata |
| /api/canvas/files/{file_id} | 单个文件 metadata |

没有凭据时，status 返回 HTTP 200、`configured=false`、`connected=false`；其余 Canvas API 返回 503。配置存在时 status 实际访问 Canvas，失败返回相应安全错误。文件 metadata 可能含短期签名下载链接，不应公开共享响应。

没有暴露通过 GET 写入本地磁盘的下载 API。下载由本地代码显式调用，供后续 SyncService 使用：

```python
from app.core.config import Settings
from app.services.canvas_service import CanvasService
from app.services.material_paths import MaterialContext

with CanvasService(Settings()) as canvas:
    context = MaterialContext(semester.year, semester.term, course.code, course.name, module.name)
    path = canvas.download_file(file_id=123, context=context)  # 使用实际上下文和 File ID
```

## 分页、超时与错误

所有 list 方法共用 `_get_paginated()`。第一页请求 per_page=100，后续原样使用 Link 中 rel=next 的查询参数，不自行递增页码。空页仍会检查 next。跟踪已访问 URL，并设置最大页数；达到保护条件报告错误，不静默截断数据。分页 URL 必须保持同一 HTTPS origin 和 API 路径，防止将 Bearer Token 发到其他站点。

每次 HTTP 请求设置统一 timeout（默认 20 秒，含连接、读取、写入、连接池等待）。这是每次网络等待的超时，不是整个分页任务或下载的总时长上限。默认不自动重试，429 会向调用方返回合理的 Retry-After（如上游提供，限定 1–3600 秒）；后续调度器决定何时重试。

| 情况 | 项目异常 / API HTTP |
| --- | --- |
| 未配置 / 非法 Canvas origin | CanvasConfigurationError / 503 |
| 401 | CanvasAuthenticationError / 401 |
| 403 / 文件锁定 | CanvasPermissionError / 403 |
| 404 | CanvasNotFoundError / 404 |
| 429 | CanvasRateLimitError / 429 |
| timeout、DNS、连接/流中断 | CanvasConnectionError / 504 |
| 5xx、非法 JSON/schema、异常分页 | CanvasError / 502 |
| 下载尺寸、重定向、存储错误 | CanvasDownloadError / 502 |

日志只使用操作名称、数值 ID、数量和状态码。不要对生产请求启用第三方 HTTP wire/debug 日志，以免记录带签名的 URL。

## 下载保护

- 只执行 HTTP GET；认证 header 仅发送到配置的 Canvas origin。
- CDN 下载及每次重定向重新判断 origin，外站不带 Canvas Token；拒绝 HTTP 降级或含嵌入凭据的 URL。
- 最多处理 5 次跳转后获取文件（最多 6 次请求），检测循环；完整文件要求 HTTP 200。
- 默认保存于 `materials/<year>-<term>/<course>/<module>/<filename>`，保留正常原始文件名；同名使用 (2) 等后缀，绝不按文件名推断资源身份。
- 路径构建、Windows 兼容、原子发布、临时目录、Resource.local_path 与后续更新约定见 [资料存储说明](material-storage.md)。
- 下载分块写入 materials 外的 staging；检查大小与上限，失败不替换旧资料。

## 真实验证

在 backend 运行 `python -m app.check_canvas`。它先测试连接和 courses，再最多抽查 3 门课程、每门 5 个 modules，直到读取一条 File metadata。只输出数量和覆盖结果，不修改 Canvas、不保存数据库、不下载文件。

退出码：0 表示所有抽样层级验证成功；1 表示安全报告的 Canvas 错误；2 表示缺少凭据或抽样未找到可访问文件，覆盖未完成。真实集成已于 2026-09-22 完成验证，包含一次 PDF 下载；公开汇总见 [V1 验证记录](v1-release.md)，详细课程报告仅保留在本地。

参考：[Canvas pagination](https://developerdocs.instructure.com/services/canvas/basics/file.pagination)、[Modules](https://developerdocs.instructure.com/services/canvas/resources/modules)、[Files](https://developerdocs.instructure.com/services/canvas/resources/files)、[Courses](https://developerdocs.instructure.com/services/canvas/resources/courses)。
