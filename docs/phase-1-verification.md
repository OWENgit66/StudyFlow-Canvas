# Phase 1 验证记录

日期：2026-09-22。范围仅限项目基础环境。

## 实际环境

- Windows / PowerShell
- Node.js 24.14.0，npm 11.9.0
- Python 3.12.8（项目内 `backend/.venv`）
- Next.js 16.3.5，React 19.2.8，Tailwind CSS 4
- FastAPI 0.141.1，Uvicorn 0.53.0

## 结果

| 检查 | 实际结果 |
| --- | --- |
| 前端依赖安装 | 成功，安装时 npm audit 报告 0 vulnerabilities |
| 后端依赖安装 | 成功，已保存固定版本 requirements.txt |
| `python -m pip check` | No broken requirements found |
| `npm run lint` | 退出码 0 |
| `npm run build` | 退出码 0，生产构建、类型检查、静态页面生成成功 |
| `npm run typecheck` | 退出码 0 |
| Uvicorn 启动 | Application startup complete，127.0.0.1:8000 |
| `GET /health` | HTTP 200，`{"status":"ok"}` |
| `GET /openapi.json` | StudyFlow API，仅包含业务路由 `/health` |
| `GET /docs` | HTTP 200 |
| Next.js 开发服务 | Ready，127.0.0.1:3000 |
| `GET /` | HTTP 200，HTML 包含 StudyFlow h1 |
| 页面引用的 CSS | HTTP 200，包含页面使用的 `.text-teal-700` Tailwind utility |

本阶段验证了开发服务与生产构建，未单独启动生产服务，也未进行浏览器视觉检查。没有 Canvas、AI 或数据库端到端验证，因为这些功能尚未实现。

## 已处理的环境问题

- npm 默认离线缓存无法获取初始化工具：通过权限机制允许下载后，初始化及依赖安装成功。
- Python ensurepip 无法写入受限临时目录：通过权限机制重建项目虚拟环境并完成安装。
- Next.js 在沙箱内构建时，TypeScript 子进程出现 `spawn EPERM`：授权后运行相同构建命令，构建及独立类型检查通过。
- 初始化工具的 ESLint 9 安装提示版本不再受维护；它是当前脚手架提供的主版本。实际 lint 通过，安装时 audit 未发现漏洞。后续更新框架时一并检查兼容性。

## 阶段边界

已保留根目录 AGENTS.md 作为长期规则，未实现 Phase 2 或后续阶段。生成目录（node_modules、.next、.venv、缓存）和敏感环境文件均在忽略规则内。
