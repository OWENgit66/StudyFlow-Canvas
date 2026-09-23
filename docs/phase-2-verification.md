# Phase 2 验证报告

日期：2026-09-22。只完成 Database Foundation；未进入 Phase 3。

## 开始前的 Phase 1 复验

- 已重新阅读根目录 AGENTS.md，检查实际仓库文件。
- 后端 app 导入成功；`pip check` 无冲突；运行中的 `/health` 返回正常。
- 前端首页 HTTP 200，`npm run lint` 和 `npm run build` 退出码均为 0，构建包含 TypeScript 检查。
- 通过以上检查后才开始数据库实现。

## 自动测试

在 backend 执行 `.venv\Scripts\python.exe -m pytest -q`：**60 passed**。

- `test_database.py`：连接、9 张表、磁盘创建与重新打开、所有实体创建、双向 ORM 关系、JSON 原地修改、UTC 时间、updated_at、去重、外键、跨周来源一致性、CHECK 约束、seed 幂等、Session 回滚。
- `test_schemas.py`：9 组 Create → ORM → Read → JSON 往返，以及非法字段和状态校验。
- `test_api.py`：5 个读取 API、空数据库、空周列表、404、422、分页、OpenAPI 与 health 回归。
- `test_config.py`：.env 加载、环境变量优先级、与 cwd 无关的数据库路径、非 SQLite URL 拒绝。

每例内存库独立；文件测试使用临时目录。测试不会读写正式开发数据。

## 实际进程和数据库验证

- `python -m app.init_db` 成功创建根目录 `data/studyflow.db`，检查得到 9 张表。
- `python -m app.seed` 成功添加 1 个学期、1 门课程、2 个周、1 条资源元数据；无真实文件或 Canvas ID。
- SQLite `PRAGMA integrity_check` 返回 `ok`；`PRAGMA foreign_key_check` 返回空列表。
- 重启 Uvicorn 后确认 OpenAPI 版本为 0.2.0，排除仍请求旧进程的可能。
- 实际 HTTP 请求 `/api/semesters`、`/api/courses`、`/api/courses/1`、`/api/courses/1/weeks`、`/api/weeks/2` 均返回 200 及正确的示例数据。
- `/health` 仍为 HTTP 200，内容 `{"status":"ok"}`。
- 前端服务仍返回 HTTP 200；本阶段未修改前端源代码。
- 最终 `pip check` 返回 `No broken requirements found`。

## 修复与已知限制

- 依赖下载、pytest 临时目录受 Windows 沙箱限制，通过权限机制执行后正常。
- 当前 Starlette 的测试客户端使用 httpx2，已替换旧 httpx 并清理中断卸载残留。依据：[Starlette TestClient 文档](https://www.starlette.io/testclient/)。
- Starlette 1.6 内部仍引用 AnyIO 的已弃用 BlockingPortal 别名。只对这条来自 starlette.testclient 的弃用告警设置精确过滤；其他告警（含 SQLAlchemy）仍按错误处理。后续升级 Starlette 时可移除此兼容项。
- `create_all()` 不负责迁移已有表。这是本阶段选择的明确边界，无未解决的运行或测试错误。
