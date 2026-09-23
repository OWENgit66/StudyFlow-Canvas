# Phase 3 验证报告

更新：下文记录的是最初无凭据时的 mock 验证。后续真实只读链路已成功通过，公开汇总见 [V1 验证记录](v1-release.md)，详细真实验证报告仅保留在本地。

日期：2026-09-22。范围：Canvas 只读集成，不进入 Phase 4。

## 开始前

重新读取 AGENTS.md 并检查文件。当前目录没有 `.git`，因此不能提供 Git diff/status；未擅自初始化 Git。已有前后端、数据库与文档保持原结构。

先运行原有 Backend tests：**60 passed**；pip check 无冲突。运行中的 `/health`、数据库课程 API、前端首页均返回 HTTP 200，之后才实现 Canvas 集成。

## 实现与测试

新增 60 项 mock / API / 下载测试，全部 Backend tests：**120 passed in 1.04s**。

覆盖：

- courses、modules、module items、course files、file metadata、字段标准化与 CourseCreate mapping。
- 常见非 File 类型、未知 item 类型、缺失 content_id、受限课程 metadata。
- 四种 list 方法的两页合并、不透明 next query、循环、最大页数、外站分页阻止。
- 认证 header 和请求 timeout；401 / 403 / 404 / 429 / 5xx、网络连接失败、读取中断、无效 JSON/schema。
- 429 不自动重试；Retry-After 传递；错误和本项目日志不泄露测试 Token。
- 安全文件名、路径穿越、Unicode、Windows 保留名、流式下载、重复下载不覆盖、CDN 不携带 Token。
- 下载失败清理、metadata 大小不符、流中大小超限、404、锁定文件、缺失 URL、重定向循环及上限、HTTPS 降级拒绝。
- 新增 6 个 GET API、状态检查、缺少凭据时原有 API 与 health 正常。

全部 Canvas 请求由 httpx2.MockTransport 接管，下载位于 pytest tmp_path；没有真实课程下载，也没有修改开发数据库。

首次运行出现 3 个 status API 测试失败：依赖 override 直接使用带 **kwargs 的工厂导致 FastAPI 将参数视为 query。改为无参数 lambda 后重跑，120 项全部通过，未禁用失败测试。

## 实际进程验证

- 重启 Uvicorn 成功；OpenAPI 版本为 0.3.0。
- `/health`：HTTP 200，`{"status":"ok"}`。
- 原有 5 个数据库读取 API：全部 HTTP 200，示例数据保留。
- `/api/canvas/status`：HTTP 200，configured=false、connected=false，明确提示未配置凭据。
- `/api/canvas/courses`：HTTP 503，安全错误 code=canvas_not_configured。
- 前端首页：HTTP 200；npm run lint、npm run build 均通过，构建含 TypeScript 检查。本阶段未修改前端源码。
- pip check：No broken requirements found。

## 真实 Canvas 验证状态

仅检查配置是否存在，没有打印值。当前 BASE_URL 和 ACCESS_TOKEN 均未配置。已运行 `python -m app.check_canvas`，报告：Real Canvas integration not verified: credentials are not configured。

**真实 Canvas 连接、实际课程/模块/文件 metadata 与真实下载均未验证。** 需要用户在本地配置 `.env` 后显式运行只读检查程序。Mock 通过不代表真实凭据或学校权限可用。

无未解决的测试或启动错误。硬链接存储需求、分页/下载上限和无自动 retry 的行为见 canvas.md。Phase 2 已有的 Starlette/AnyIO 精确弃用过滤保留，未扩大告警过滤范围。
