你现在是我的 **Senior Full-Stack Engineer + AI Engineer + Software Architect**。

我要你帮助我从 0 开始设计并实现一个完整的个人项目，项目暂定名：

# StudyFlow

这是一个面向大学生的 **AI 自动课程学习平台**。

它的核心目标是：

> 自动从 Canvas LMS 获取我的课程课件，按照 Semester → Course → Week 进行整理，解析 PDF/PPTX/DOCX 内容，使用 AI 提炼知识点，并最终通过一个结构清晰、漂亮、方便学习的网页进行展示。

我希望最终这个项目不仅能够自己使用，也可以作为我的 AI Application / Full-Stack / RAG Portfolio Project。

---

# 一、核心 Workflow

系统的整体流程应该是：

Canvas LMS

↓

获取当前 Semester 的 Courses

↓

读取每门课程的 Modules / Weeks

↓

读取其中的 Files / Lecture Slides / Tutorials

↓

检查哪些文件是新增的或已经更新

↓

下载文件到本地 Storage

↓

解析 PDF / PPTX / DOCX

↓

提取文字、标题、页码、表格等信息

↓

按照合理长度切分 Document Chunks

↓

调用 LLM 分析课件

↓

生成结构化知识

↓

存入数据库

↓

在网页中按照：

Semester
→ Course
→ Week
→ Resource
→ Knowledge

进行展示。

---

# 二、MVP 范围

请不要一开始过度设计。

第一版 MVP 只需要支持：

1. 单用户
2. 一个 Semester
3. 多门 Course
4. Canvas API 获取课程
5. Canvas Modules 获取 Week
6. Canvas Files 下载课件
7. PDF 解析
8. AI 自动总结
9. SQLite 数据库
10. 网页 Dashboard
11. Course 页面
12. Week 页面
13. 原始课件查看/下载
14. 手动点击 “Sync Canvas” 开始同步

第一版暂时不要实现：

* 多用户系统
* 手机 App
* 微服务
* Redis
* Kafka
* Kubernetes
* 复杂权限系统
* 社交功能
* 自动部署集群
* 复杂知识图谱

先保证完整 Workflow 可以真正运行。

---

# 三、推荐技术栈

除非你发现有明显更合理的方案，否则优先使用：

## Frontend

Next.js
TypeScript
Tailwind CSS

## Backend

Python
FastAPI

## Database

MVP：

SQLite

后续：

PostgreSQL

## Document Parsing

PDF：

PyMuPDF

后续支持：

python-pptx
python-docx

## AI

设计一个统一：

LLMService

不要把整个项目和某一家模型 API 强绑定。

应该方便以后更换：

OpenAI
Gemini
Claude
Local Model

## Canvas

优先使用 Canvas REST API。

创建：

CanvasService

负责：

get_courses()

get_modules()

get_module_items()

get_files()

download_file()

不要一开始使用 Selenium 或 Playwright。

只有当 Canvas API 无法完成某个功能时才考虑 Browser Automation。

---

# 四、建议项目架构

项目建议采用：

studyflow/

frontend/

backend/

data/

docs/

README.md

backend 内建议：

app/

api/

services/

models/

schemas/

repositories/

core/

utils/

services 至少包含：

CanvasService

DocumentService

AIService

SyncService

KnowledgeService

---

# 五、数据库设计

至少设计这些实体：

Semester

Course

Week

Resource

DocumentChunk

Summary

Concept

Question

SyncRecord

建议关系：

Semester

↓

Course

↓

Week

↓

Resource

↓

DocumentChunk

同时 Week 可以关联：

Summary

Concept

Question

Course 至少包含：

id

canvas_course_id

code

name

semester_id

Week 至少包含：

id

course_id

week_number

title

Resource 至少包含：

id

canvas_file_id

week_id

filename

file_type

local_path

canvas_updated_at

sync_status

DocumentChunk 至少包含：

id

resource_id

page_number

chunk_index

content

Concept 至少包含：

id

week_id

resource_id

name

definition

explanation

importance

source_page

Summary 至少包含：

id

week_id

overview

key_points

exam_focus

Question 至少包含：

id

week_id

question

answer

source_page

请根据实际工程需要进一步优化 schema。

---

# 六、AI Knowledge Engine

不要简单让 LLM 输出一篇长文章。

LLM 应该返回严格的结构化 JSON。

例如：

{
"topic": "Time Management",

"overview": "本周主要介绍……",

"concepts": [
{
"name": "Critical Path",
"definition": "...",
"explanation": "...",
"importance": "high",
"source_pages": [15,16]
}
],

"key_points": [
"...",
"..."
],

"formulas": [
{
"formula": "EF = ES + Duration",
"explanation": "...",
"source_page": 20
}
],

"examples": [],

"exam_focus": [],

"questions": [
{
"question": "...",
"answer": "...",
"source_page": 18
}
]
}

必须：

1. 使用 schema validation
2. 处理 LLM JSON 输出错误
3. 尽量保存知识点对应的 source page
4. 不允许 AI 编造课件中不存在的知识
5. 如果课件没有相关信息，应明确为空

---

# 七、网页设计

我希望网页是一个：

Clean / Modern / Academic / Minimal

风格的学习 Dashboard。

不要做成传统后台管理系统。

首页 Dashboard 应该显示：

StudyFlow

Current Semester

Courses

例如：

COMPXXXX
Computer Networks

Progress: 5 / 13 Weeks

Latest:
Week 5 – Network Layer

进入课程：

COMPXXXX

Week 01
Introduction

Week 02
Link Layer

Week 03
CRC

...

点击 Week：

应该展示：

Week Title

Overview

Key Concepts

Key Points

Formulas

Examples

Exam Focus

Practice Questions

Original Materials

例如：

Key Concepts

CRC

Definition:
...

Explanation:
...

Importance:
★★★★★

Source:
Lecture Week 2 – Page 32

用户点击 Source 后以后可以跳到原 PDF 页。

---

# 八、Sync Canvas

网页中应该有：

Sync Canvas

按钮。

点击后：

Frontend

↓

POST /api/sync

↓

SyncService

↓

CanvasService

↓

获取课程

↓

获取 Modules

↓

获取 Files

↓

检查 Canvas File ID

↓

检查 updated_at

↓

如果没有变化：
Skip

如果是新文件：
Download

如果发生更新：
Replace

↓

DocumentService

↓

AIService

↓

Database

↓

Frontend Refresh

必须实现同步日志，例如：

INFO6007 Week 3 Lecture

Downloaded

↓

Parsed

↓

AI Processing

↓

Completed

如果失败：

Failed

并记录错误原因。

---

# 九、非常重要：增量同步

不要每一次 Sync 都重新分析所有课件。

应该通过：

canvas_file_id

*

canvas_updated_at

或其他可靠信息判断文件是否发生变化。

如果：

Canvas 文件没有变化

则：

Skip download
Skip parsing
Skip AI analysis

避免浪费时间和 LLM API Token。

---

# 十、配置和 Secrets

Canvas Token

LLM API Key

Database URL

等信息必须放：

.env

并提供：

.env.example

例如：

CANVAS_BASE_URL=

CANVAS_ACCESS_TOKEN=

LLM_PROVIDER=

OPENAI_API_KEY=

DATABASE_URL=

禁止：

把 Token

API Key

Password

写进 Git Repository。

---

# 十一、错误处理

系统必须考虑：

Canvas API timeout

Canvas token invalid

文件下载失败

PDF 无法解析

PDF 没有文本

LLM API timeout

LLM 返回错误 JSON

数据库错误

AI Rate Limit

某个文件失败不能导致整个 Sync 任务全部崩溃。

应该：

记录错误

继续处理其他文件

最后给出 Sync Summary。

例如：

Sync Completed

Courses: 4

Files discovered: 26

New: 3

Updated: 1

Skipped: 22

Failed: 1

---

# 十二、未来 RAG

MVP 完成之后，再增加：

Embedding

Vector Database

Semantic Search

RAG Chat

目标是让我可以问：

“CRC 是什么？”

系统自动：

Query

↓

Embedding

↓

搜索 DocumentChunks

↓

找到：

COMPXXXX

Week 2

Lecture

Page 32–38

↓

LLM

↓

回答

并显示：

Sources

COMPXXXX
Week 2 Lecture
Page 32–38

未来 Vector Database 可以考虑：

pgvector

但是 MVP 阶段不要急着加入。

---

# 十三、未来功能

基础系统完成后可以逐步增加：

Global Search

RAG Chat

Flashcards

Quiz Generator

Revision Mode

Exam Mode

Knowledge Graph

Learning Progress

Bookmarks

Notes

Dark Mode

Study Statistics

例如：

AI 自动根据本周知识点生成：

5 Multiple Choice Questions

3 Short Answer Questions

2 Calculation Questions

---

# 十四、代码质量要求

代码应该：

模块化

易读

可维护

有合理注释

遵循 Python / TypeScript 最佳实践

不要把所有代码写在一个文件。

Service、Database、API、Schema 要合理分层。

避免：

God Class

巨大函数

大量重复代码

Hard-coded configuration

---

# 十五、README

项目必须最终包含完整 README：

1. Project Introduction
2. Features
3. Architecture
4. Tech Stack
5. Project Structure
6. Installation
7. Environment Variables
8. Canvas Setup
9. LLM Setup
10. Running Backend
11. Running Frontend
12. Screenshots
13. API Overview
14. Future Roadmap

目标是让我以后可以把这个项目直接放到 GitHub Portfolio。

---

# 十六、开发方式

你不是只给我代码示例。

你的任务是：

真正把这个项目完成。

如果你拥有文件操作、Terminal、Git 或 Coding Agent 能力：

请直接：

创建文件夹

创建文件

安装依赖

编写代码

运行代码

检查错误

修复错误

运行测试

而不是每一步都让我手动复制代码。

---

# 十七、开发阶段

严格按照以下阶段开发：

Phase 1

Project Setup

完成：

frontend

backend

.gitignore

.env.example

README

基础运行环境

---

Phase 2

Database

完成：

Semester

Course

Week

Resource

DocumentChunk

Summary

Concept

Question

SyncRecord

并测试数据库连接。

---

Phase 3

Canvas Integration

完成：

CanvasService

能够：

获取 Courses

获取 Modules

获取 Module Items

获取 Files

下载文件

先写测试程序验证 Canvas API。

---

Phase 4

Document Parser

先实现：

PDF parsing

输出：

page_number

text

metadata

然后实现 chunking。

---

Phase 5

AI Knowledge Engine

实现：

AIService

结构化 JSON Output

Schema Validation

生成：

Overview

Concepts

Key Points

Formulas

Exam Focus

Questions

---

Phase 6

Sync Pipeline

实现完整：

Canvas

→ Download

→ Parse

→ AI

→ Database

完整 workflow。

---

Phase 7

Frontend

实现：

Dashboard

Course Page

Week Page

Resource Display

Sync Canvas Button

Sync Status

---

Phase 8

Testing & Polish

运行：

Backend Tests

API Tests

Frontend Tests

Manual Workflow Test

修复：

Broken UI

Broken API

Error Handling

---

Phase 9

RAG

只有前面全部运行正常后再开始。

---

# 十八、你的工作方式

非常重要：

不要一次生成大量未经验证的代码。

对于每一个 Phase：

先检查当前项目状态。

然后：

Implement

↓

Run

↓

Test

↓

Fix

↓

确认当前阶段正常

↓

再进入下一阶段。

如果出现错误：

先自己分析错误日志并修复。

不要简单把错误扔给我让我解决。

如果你能够运行 Terminal：

请真正运行命令验证。

不要说：

“This should work.”

而应该实际确认：

“This works.”

---

# 十九、不要随意改变项目目标

如果发现某个技术选择有问题：

先说明：

Current approach

Problem

Recommended change

Reason

然后再修改。

不要因为实现起来比较麻烦就擅自删除核心需求。

---

# 二十、第一步

现在请先不要一次把整个项目代码全部生成出来。

首先完成：

1. 分析整个需求
2. 给出最终系统架构
3. 给出完整目录结构
4. 给出 Database Schema
5. 给出 API 设计
6. 给出 Canvas → AI → Database → Frontend 的数据流
7. 给出 MVP Development Plan
8. 指出可能存在的技术风险

完成这些之后：

如果当前环境允许你直接操作项目文件，请立即开始 Phase 1，并建立实际项目。

如果你是 Coding Agent：

从此之后请把自己当成该项目的 Lead Engineer，持续检查整个 Repository 的状态，不要孤立地修改单个文件。

最终目标不是“给我一些示例代码”。

最终目标是：

# 交付一个真正可以运行的 StudyFlow MVP。
