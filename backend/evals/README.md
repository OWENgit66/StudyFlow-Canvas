# Resource classification evaluation（离线）

这里只评测生产函数 `app.services.material_classification.classify_resource_type`，不复制规则，不启动应用或 SyncService，不读取配置/凭据、数据库或 PDF，不调用 Canvas/LLM。数据准备与评测执行分开；评测只读取指定 JSON。

## 运行

在 `backend` 目录：

```powershell
.venv\Scripts\python.exe -m evals.resource_classification --split regression --dataset ../data/classification-baseline/resource_classification_gold.json --output ../data/classification-baseline/regression-results.json
```

跨平台、已激活环境时可使用 `python -m evals.resource_classification ...`。

真实课程 metadata 和结果位于 Git 已忽略的 `data/classification-baseline/`。它们不会随仓库发布。公开合成示例只用来演示格式，不代表真实准确率：

```powershell
.venv\Scripts\python.exe -m evals.resource_classification --dataset evals/resource_classification_example.json
.venv\Scripts\python.exe -m pytest -q tests/test_classification_eval.py
```

## Development / Regression 与 Holdout

- V2.1 baseline：27/30（90%），历史结果保存在 `baseline-results.json`。
- V2.2a regression：30/30（100%），使用同一份已参与规则调整的 development/regression 集。这不是 unseen accuracy。
- V2.2a holdout：**pending**，目前没有人工标注样本，不能据此报告准确率。

独立私有数据集为 `data/classification-holdout/resource_classification_holdout.json`，当前内容为 `[]`。此目录同样被 Git 忽略；新 checkout 可在该路径手工创建一个内容为 `[]` 的 JSON 文件。不要覆盖原 30 条 regression 标签，也不要覆盖历史 baseline 报告。

在 `backend` 目录运行 holdout：

```powershell
.venv\Scripts\python.exe -m evals.resource_classification --split holdout --dataset ../data/classification-holdout/resource_classification_holdout.json --output ../data/classification-holdout/holdout-results.json
```

空数组正常返回 0，并提示 `No holdout samples available.`，总数为 0、准确率为 N/A。非空文件仍使用相同的严格标签/metadata 校验；格式错误不会被当成空数据集。默认 `--split regression` 继续要求非空数据。

每次只评测 `--dataset` 指定的一组数据，不合并其他样本。终端和 JSON 的 `split` 字段区分 regression 与 holdout；holdout 预测字段为 `predicted_type`。Regression 为兼容既有报告保留 `v2_1_prediction` 字段名，但两种模式都调用**当前生产 classifier**，不会加载旧版本规则。

添加 holdout 样本时，按下方相同格式追加对象，建议 ID 使用 `holdout-001` 等。只使用未参与 V2.2a 调整、且未出现在 regression 集中的真实文件；检查文件身份/来源，不能仅换一个 sample_id 重复已有资源。根据教育用途人工标注后再查看预测，保留可选 `source`/`annotation_note` 便于复核。不要依据 holdout 错误调整本次分类规则，也不要将合成测试用例加入真实 holdout。

## 添加人工标注样本

Gold 文件是 JSON 数组。复制一个对象，设置唯一字符串 `sample_id`，填写真实可用 metadata，并根据材料的教育用途独立标注 `expected_type`：

```json
{
  "sample_id": "new-001",
  "filename": "Week5.pdf",
  "module_name": "Week 5 Tutorial",
  "page_title": "Week 5 Exercises",
  "link_title": "",
  "nearby_text": "",
  "expected_type": "tutorial"
}
```

标签只能是 `lecture`、`tutorial`、`other`。Metadata 可以为空字符串、null 或缺省，不得编造缺失上下文。另支持可选 `item_title`、`display_name`，分别映射生产函数的同名参数。`module_name` 映射 `module_title`，`link_title` 映射 `link_text`；其余同名传入。`source`、`annotation_note` 等溯源/标注说明不会传给分类器。

不要将预测结果、数据库中默认的 `resource_type=other` 当作 gold。先标注、再运行；不确定真实用途的候选应待人工核实后再加入，不能仅因难以判断就标为 other。不要为了提高指标改标签；纠正真实标注错误时记录原因。建议每个真实文件只保留一个样本，避免同一文件多次出现放大权重。

## 初始样本的边界

初始私有集包含 30 个唯一文件，三个类别各 10 个，来自 5 门课程：26 条使用本地 Resource/Week metadata，4 条使用先前保存的 Canvas Page 与文件 metadata。未查询既有 `resource_type` 作为标签，未请求 Canvas、未解析 PDF。样本由本次开发根据显式标题/上下文独立整理标注，**尚未经项目所有者人工确认**。Gold 内保留来源与标注理由，供逐条复核。

这是方便检查的平衡抽样，不是随机代表性采样，也不是完整线上 sync 的端到端准确率。缺失的 Item/Page/display-name metadata 留空；线上可用的更多上下文可能改变预测。对包含多个发现上下文的同一文件，当前格式只评测记录的上下文，不模拟 sync 的跨链接合并。两条阅读材料属于 role classifier 的 other 样本；正常 sync 的阅读过滤会先跳过它们，因此其 role 错分不等于线上一定会下载或分析阅读资料。

## 输出与测试

输出总数、正确/错误数、总体准确率，以及按 **expected_type** 分组的正确数/总数（无样本时 N/A）。每个样本输出 `sample_id`、`expected_type`、`v2_1_prediction`、`correct`；错误样本另列文件名。可选 JSON 结果附 gold 与 classifier 文件 SHA-256，便于固定 baseline。脚本不会写回 gold，禁止将输出路径设为 gold 路径。

错分属于测量结果，执行成功仍返回 0；非法数据或参数报错。测试只验证数据校验、生产函数调用/字段映射、指标、逐项结果、错误输出与离线执行，不要求分类达到某个百分比。本任务不运行完整后端/前端验收。
