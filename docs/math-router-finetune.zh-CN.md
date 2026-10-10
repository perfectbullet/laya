# MongoDB 数学路由微调说明

本文解释本项目数学路由的数据与标签，不是英文指南的翻译。先读 [中文微调指南](finetune.zh-CN.md)，再结合本说明理解数据准备。部署条件见仓库根目录的 `DEPLOYMENT_REPORT_2026-10-09_CORRECTION.md`。

## capability-v1 的含义

`question_capabilities` 是题目本地处理能力的汇总集合。`capabilityVersion: "capability-v1"` 是这套能力评测记录的版本标记，不是模型名称、题目难度或 Laya checkpoint。

“以 capability-v1 为标签依据”表示：选取这个版本的能力记录，将本地实际推理和评测的汇总结果转换成路由训练标签。它不表示可以省略对汇总结果的核查。

需要关注的字段：

| 字段 | 含义或用途 |
|---|---|
| `questionId` | 关联 `questions.id`，例如 `MATH-001` |
| `capabilityVersion` | 能力记录版本，当前选择 `capability-v1` |
| `labelUsable` | 该题的能力标签是否可用于训练 |
| `attempts`、`gradableAttempts` | 本地尝试数、可评测尝试数 |
| `localSuccessCount`、`localSuccessRate` | 本地成功数与成功比例 |
| `attemptDetails` | 各次运行和评测结果的核查依据 |
| `runtime` | 完成、截断、失败等运行状态汇总 |

按当前三轮实验，初始映射为：

```text
labelUsable = true，三个有效尝试全部成功且没有运行异常 → local
labelUsable = true，本地存在失败                          → online
labelUsable = false                                      → 排除，待复核
```

导出时应核对 `localSuccessRate == 1.0`、三轮尝试、逐次结果和运行状态是否一致；发现异常则单独报告。已知本地截断题按 online 处理。若汇总字段相互矛盾，应核查对应 runs / evaluations 后再定标签。

2026-10-10 的只读查询结果：250 道题，240 道标签可用，其中 220 道成功比例为 1.0、20 道不足 1.0；10 道标签不可用。该版本 `runtime` 汇总中的 truncated 和 failed 合计均为 0。标签不可用题不能仅凭成功比例当作已确定标签。

## JSONL 中两个 math_route 的区别

`math_route` 是自定义的任务 ID，用来关联问题定义与正确答案；它不是数学题 ID，也不是内置 typed-decisions 工作流。

- `questions.math_route`：固定的完整问题定义，包括 `type`、`instructions` 和 `criteria`；所有训练题使用相同定义。
- `expected.math_route`：该道题的正确路由标签，由能力记录生成，值为 `local` 或 `online`。

下面是结构完整的示例。题面与标签仅为说明格式，实际应以 MongoDB 中同一道题的记录填充：

```json
{
  "state": "求方程 x² − 5x + 6 = 0 的解。",
  "questions": {
    "math_route": {
      "type": "choice",
      "instructions": "仅根据数学题题面，判断是否适合交给本地数学模型处理。稳定可靠时选择 local；存在出错风险或无法确认时选择 online。不要解题，不要输出答案或解释。",
      "criteria": {
        "local": "本地数学模型可稳定正确处理。",
        "online": "本地处理存在风险，应交给在线数学模型。"
      }
    }
  },
  "expected": {"math_route": "local"}
}
```

上例展开为多行便于阅读；实际 JSONL 一条样本占一行。上次对话中 `{"math_route": "使用上面的完整问题定义"}` 是占位示意，不能作为可训练的真实数据。

每条记录的 `state` 取自 `questions.question`；`questions.math_route` 来自固定任务定义；`expected.math_route` 来自关联的 `question_capabilities` 记录。若该题存在本地失败，示例最后的 `local` 改为 `online`。

## 标签不能来自 Laya 自己的预测

不使用 `laya_math_route_experiments` 中的预测结果、人工难度字段，或 Laya 的 `probabilities.simple` 作为本次正确标签。已有零样本实验可作为对照，但训练监督来自本地实际表现。

本地三次全对不等于题目在数学上简单，因此建议微调任务使用 `math_route: local/online`。既有 `math_difficulty: simple/difficult` 的 v3 提示词与 0.70 门槛保留为零样本基线。

每道题只生成一条样本；三轮 runs 是生成这一条标签的证据，不能拆成三条后随机切分。模型输入不含参考答案、历史推理过程、评测理由或能力字段。

## 训练、校准与评估

240 道题只有 20 道风险题，直接全部预测 local 就有 91.67% 分类准确率，因此整体分类准确率不能衡量路由是否安全。

建议在开发阶段按题目分层做五折验证；完全相同的题或明确同源变式放在同一组。训练部分内部再留出校准数据，并检查风险类数量。当前 `split_calibration` 默认随机抽取，不保证类别分层；需要在后续包装流程中明确处理。

校准与评估重点是本地覆盖率、风险误放行数，以及放行集合中历史本地三次均正确的比例。模型训练后的概率分布会改变，不能直接继承零样本模型的 0.70 阈值，应在校准数据上重新选择 `P(local)` 门槛。

这些题已经用于多轮提示词调试，因此现有数据上的验证属于开发评估。上线前需要新增未参与训练、提示词选择和阈值选择的题目。三次全对标签也不等于已证明未知题真实成功率达到 98%。

## 训练环境与下一步

部署报告显示，233 使用支持 V100 的 CUDA 12.6 PyTorch 环境，模型已离线缓存；实际训练前仍需核查可用显存、磁盘和在线服务安排。230 在驱动修复前不适合 CUDA 训练。

计划的数据流程是：只读查询 MongoDB → 生成可追溯标签与题目切分 → 导出 JSONL → dry-run 检查 → 比较冻结编码器和全参数微调 → 校准 → 评估 → 决定是否部署。

训练产物应写入独立目录，例如 `/data/metahuman_work/laya-finetunes/<run-id>`，保留任务定义原文、哈希、切分清单与标签版本。以下数据已导出，但尚未启动训练。

## 已准备的数据与复现方法

2026-10-10 已通过 `scripts/prepare_math_route_data.py` 只读导出到仓库的 `data/math-router/capability-v1-20261010/`。该目录已加入 Git 忽略规则。导出包含 240 条样本（220 local、20 online）；另有 10 条标签不可用记录排除。

| 文件 | 用途 |
|---|---|
| `questions.json` | 固定的 `math_route` 完整问题定义 |
| `all_labeled.jsonl` | 全部可用样本；不能直接作为独立验证训练输入 |
| `label_audit.jsonl` | 题目 ID、标签依据、原始能力证据、题面哈希与分组 |
| `excluded.jsonl` | 排除题目 ID 和原因 |
| `manifest.json` | 种子、提示词版本/哈希、源版本、五折 ID 清单及各文件校验和 |
| `fold-0/` 至 `fold-4/` | 各折的 `train.jsonl`、`calibration.jsonl`、`test.jsonl` |

每折训练 144 条（132 local、12 online），校准 48 条（44 local、4 online），测试 48 条（44 local、4 online）。每道题恰好一次作为测试题、一次作为校准题；在同一折中三个集合互不重叠。

默认分组使用 Unicode NFKC 与空白规范化后的完全相同文本，并尝试平衡标签和题型。未自动识别同源变式。人工审核后，可用 `--groups-file` 指定同源题组，文件格式为 `{"MATH-001": "family-a", "MATH-002": "family-a"}`。相同组的题目必须留在同一桶；分组变化可能改变各折数量。

复现时指定一个新的输出目录，脚本拒绝覆盖已有导出：

```bash
python scripts/prepare_math_route_data.py \
  --out data/math-router/capability-v1-new-export \
  --capability-version capability-v1 \
  --seed 20261010
```

离线标签与分组逻辑检查：

```bash
python scripts/test_prepare_math_route_data.py
```

注意：当前 `laya-train` 会从 `--data` 内随机留出校准集。后续训练包装脚本需要显式使用这里的 `calibration.jsonl`，不能直接把默认 CLI 的随机校准当成上述固定切分。当前只检查了标签、JSONL 结构、分组隔离和校验和；还未用 233 的基础模型 tokenizer 执行 dry-run，也未验证题面是否会被 token 预算截断。
