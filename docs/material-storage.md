# 原始资料存储

默认位置是项目根目录 `materials/`，结构如下：

```text
materials/
  <year>-<term>/
    <Course Code> - <Course Name>/
      <Canvas Module Name>/
        <Canvas filename>
```

`MATERIALS_ROOT` 未设置或为空时默认 `materials`，相对路径按项目根目录解析。也允许绝对路径。旧 `STORAGE_PATH` 保留兼容配置读取，但不再决定新课件位置；不修改用户已有 `.env`。

## 命名与安全

- Semester 来自关联的数据库 Semester.year / term，不使用固定年份，也不自动猜测多个学期中的当前学期。
- Course 使用 code - name；没有 code 时只使用 name。保留 Canvas 课程代码中的班次等信息，避免自行改变其含义。
- Module 使用真实名称；数据库 Resource 下载入口使用所属 Week.title，因此后续 Module 映射必须保留原始标题。
- 普通 filename 原样保留，包括空格与 Canvas 原始文件名中的 `+`；不自动 URL decode 或改用 display_name。
- 非法字符替换为 `_`，处理控制字符、尾部空格/点和 Windows 保留名，校验解析后的路径不能越过资料根目录。
- 为兼容 Windows Explorer，总路径预留冲突后缀空间。只有过长名称会缩短，必要时追加短哈希并保留文件扩展名。
- 不同资源同名时创建 `Lecture.pdf`、`Lecture (2).pdf` 等。按不区分大小写检查，并使用不覆盖目标的硬链接发布；不会仅根据文件名推断资源身份。
- `.partial` 在 `MATERIALS_ROOT` 同级的 `.studyflow-staging/` 内创建，成功/失败后清理，不放入 materials。存储盘需支持硬链接，已验证本机 NTFS。
- `materials/` 内只保存原始资料（仓库保留一个空目录标记），数据库、日志、chunks 和摘要继续放在各自目录。默认资料和 staging 均被 Git ignore。

## 调用方式与更新

低层 CanvasService 保持不访问数据库。下载现在要求显式提供资料上下文，避免继续生成无课程信息的测试目录：

```python
from app.services.material_paths import MaterialContext

context = MaterialContext(
    year=semester.year,
    term=semester.term,
    course_code=course.code,
    course_name=course.name,
    module_name=module.name,
)
path = canvas.download_file(file_id, context=context)
```

已有 Resource 时，使用 `app.services.material_service.download_resource(db, canvas, resource)`：从 Resource → Week → Course → Semester 构造目录，将实际下载位置写入 local_path，状态设为 downloaded。调用方负责 commit。位于项目内时保存 POSIX 风格相对路径；自定义根目录位于项目外时只能保存绝对路径，移动电脑需要调整。

有 local_path 的 Resource 更新使用它已记录的路径；不会根据同名文件寻找替换目标，也不允许替换被另一个 Resource 共用的路径。低层 `existing_path` 仅供可信调用方传入已确认归属当前 Canvas File ID 的路径，不作为对外 API。下载不完整时保留旧文件，验证成功后原子替换。若旧文件缺失，明确报错，调用方须显式选择恢复策略。

本次不判断 updated_at、不实现自动 skip。未来 SyncService 可以在调用前比较 ID / updated_at，未变化则完全跳过；更新则调用现有入口。文件发布与 SQLite 提交不是一个跨系统原子事务，未来同步任务需负责数据库提交失败后的补偿/重试。本次单文件验证的提交已成功。

## Verification

Storage tests use synthetic metadata and temporary files. Coverage includes path containment, Windows names, collisions, interrupted-download protection and resource ownership. Private live file inventories remain local. See [V1 verification](v1-release.md).
