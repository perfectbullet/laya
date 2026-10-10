# 使用自己的决策数据微调 Laya

本文译自本仓库的 [英文微调指南](finetune.md)，保留原文的训练流程、参数、示例和基准结果。基准数字属于原文中的实验，不是中文数学路由实验的成绩。数学路由的数据解释见 [MongoDB 数学路由微调说明](math-router-finetune.zh-CN.md)。

在 typed-decisions 基准中，基础 checkpoint 的零样本成绩接近随机水平：0.36 和 0.35，随机基线为 0.318。微调后的 checkpoint 在同样的 2,000 次决策上达到 **0.766**，高于 TypeSafe Jev 公布的 0.727，也高于教师自身判断一致性的参考上限 0.735。微调是重要的收益来源。[公开微调 notebook](https://github.com/NandhaKishorM/laya/blob/main/notebooks/laya_finetune_typed_decisions_2xT4_kaggle.ipynb) 在 Kaggle 的免费双 T4 GPU 上完成整个流程：构建数据、用 RLCD 训练、拟合校准温度、评估并上传 Hub。本指南说明该 notebook，也指出替换为自己的数据后仍需保留的关键环节。

同样的流程已经包含在 Python 包中：`laya-train` 可以用一条命令从 CSV 或 JSONL 标签数据在单个设备上训练，`laya.train.finetune` 提供相同的 Python 接口。下文先介绍这些接口，再介绍 notebook。

另一个使用单张 16 GB GPU、无需付费 API 的实例，见 [浏览器代理决策头微调案例（英文）](finetune_browser_agent.md)。

## 使用 laya-train 微调

`laya-train`（也可写成 `laya train`）构建训练样本，进行微调，在训练前留出的数据上拟合校准温度，并保存可由 `laya.load` 加载的 checkpoint。支持单个 CUDA、MPS 或 CPU 设备。

### 从 CSV 训练

每一行是一条决策；一列存文本，另一列存正确标签：

```bash
laya-train --data tickets.csv --text-column body --label-column department \
           --base english --out ./tickets-checkpoint
```

标签列中的不同值按首次出现顺序构成 `choice` 问题的候选项。问题 ID 由 `--question-id` 指定，默认 `label`；指令由 `--instructions` 指定。生成的问题保存在 checkpoint 旁的 `questions.json` 中。推理时，应向微调模型提出相同的问题：

```python
import json, laya

agent = laya.load("./tickets-checkpoint")
questions = json.load(open("./tickets-checkpoint/questions.json"))
print(agent.predict("We were billed twice for March.", questions)["answers"])
```

支持 Excel 导出的带字节顺序标记（BOM）的文件。文本或标签为空的行会被跳过，并统计数量。

### 从 JSONL 训练

每一行是一条样本；一条样本可以包含多个问题，问题类型也可以不同。支持两种标签结构，同一文件可混用。

下面为便于阅读进行了换行；实际 JSONL 中每条记录必须占一行。

```json
{
  "state": "We were billed twice for March.",
  "questions": {
    "department": {
      "type": "choice",
      "instructions": "Which team should handle this?",
      "criteria": {"billing": "invoices, refunds", "technical": "bugs, outages"}
    },
    "urgent": {"type": "noul", "instructions": "Does this need an answer today?"}
  },
  "expected": {"department": "billing", "urgent": true}
}
```

- `expected` 为每个问题提供一个正确答案，也是 `laya-evals` 能读取的格式，因此同一种文件格式可以用于训练和评估。`choice` 使用候选标签；`noul` 使用 `true/false`；`score` 使用等级。分数等级可以是小数，例如 `1.5` 将权重分配到等级 1 和 2。`--label-smoothing 0.1` 将答案权重的十分之一分配到其他候选项。
- `gold` 为每个问题提供教师模型给出的概率分布，也是 notebook 使用的结构，例如 `{"department": {"probabilities": {"billing": 0.9, "technical": 0.1}}}`。`noul` 的概率键为 `"false"/"true"`；`score` 使用字符串形式的等级索引。

### 长时间训练前先检查数据

```bash
laya-train --data tickets.csv --text-column body --label-column department --dry-run
```

`--dry-run` 使用 `--base` 的 tokenizer 和配置构建训练样本，不加载模型权重、不进行训练。它输出读取的行数、生成的训练样本数，以及跳过的问题数量和原因：

| 原因 | 跳过的含义 |
|---|---|
| `empty_text`、`empty_label` | 缺少文本或正确答案 |
| `invalid_question`、`invalid_target` | 无法读取问题定义或目标答案 |
| `options_collapsed` | 候选项的 token 预算不足，使两个候选项编码成相同 token（#538） |
| `options_beyond_max_len` | 问题候选项无法装入 `max_len` |

### 训练输出

`--out` 目录包含 `laya.load` 所需的 `model.safetensors`、`encoder/`、`tokenizer/`、`rl_agent_config.json`，以及 `questions.json`。每轮训练结束后还会重写 `checkpoint_latest/`，用于保留最近一轮的 checkpoint。

配置会保存本次使用的 `max_len` 和 `head_max_len`，将训练设置写入 `training.laya_train`，将校准报告写入 `training.laya_train_calibration`。校准报告按问题类型记录校准样本数量、准确率、平均置信度和需要注意的问题。训练期间也会输出警告，例如：

```text
laya.train: choice calibration: not fitted: 2 calibration items, fewer than 10, so the temperature stays 1.0
```

含义是：只有 2 个 choice 校准样本，少于最低要求的 10 个，因此不拟合温度，保持 1.0。这表示置信度尚未经过校准；应补充数据并完成校准，再依赖 `min_confidence` 门控。

### 参数

| 参数 | 默认值 | 作用 |
|---|---|---|
| `--base` | `convaiinnovations/laya` | 基础 checkpoint：本地目录、内置名称 `english/multilingual/typed-decisions` 或 Hub 仓库 ID |
| `--loss` | `rlcd` | notebook 的训练目标；`soft-ce` 仅使用软交叉熵（#741） |
| `--shuffle-options` | 关闭 | 每轮随机排列 choice 候选项，重新编码，同时调整正确答案位置 |
| `--label-smoothing` | `0.0` | 将一部分单一答案权重移到其他选项 |
| `--freeze-encoder` | 关闭 | 只训练决策头；适合小显存 GPU 或 CPU，但原文认为收益远小于全参数微调 |
| `--epochs`、`--micro-batch`、`--grad-accum` | 4、8、8 | 训练 4 轮，有效批量为 64 |
| `--encoder-lr`、`--head-lr` | 2.5e-5、1e-4 | 编码器和决策头的学习率 |
| `--max-len`、`--head-max-len` | 基础 checkpoint 的配置 | token 预算；notebook 使用 1024 和 256 |
| `--device`、`--seed` | `auto`、0 | 设备与随机种子 |

CUDA 默认启用混合精度。如果某种 GPU 上 fp16 比 fp32 慢（例如 GTX 16xx），可通过 Python 的 `TrainConfig(amp=False)` 关闭。

### 参数的实际效果

以下是原文引用 [#887](https://github.com/NandhaKishorM/laya/issues/887) 的实验：每次使用单张 T4，按 notebook 的设置对 `convaiinnovations/laya` 进行全参数微调。

typed-decisions：6,000 条训练决策、2,000 条测试决策，一个随机种子：

| 配置 | 准确率 | ECE（校准误差） | 反转选项后答案改变的比例 |
|---|---|---|---|
| 基础 checkpoint | 0.362 | 0.174 | 0.357 |
| `--loss rlcd`（默认） | 0.7715 | 0.150 | 0.065 |
| `--loss soft-ce` | 0.790 | 0.157 | 0.078 |
| `--loss soft-ce --shuffle-options` | 0.7875 | 0.159 | 0.062 |

英文 MASSIVE 意图分类：每个问题 20 个选项、11,514 条训练数据、2,974 条测试样本，每个测试样本另用 3 种打乱顺序回答；使用 `soft-ce`，每行配置运行两个种子：

| 配置 | 准确率 | 重排选项后答案改变的比例 |
|---|---|---|
| 基础 checkpoint | 0.730 | 0.187 |
| 不打乱选项 | 0.936 | 0.026 |
| 打乱选项 | 0.941 | 0.019 |

只有 4 个选项时，微调本身已经能稳定答案，打乱选项没有可测量的额外收益。20 个选项时，打乱使准确率提高约 0.55 个百分点，答案变化比例降低约四分之一，两个种子的结果均有显著改善，代价是约 14% 额外训练时间。因此，该选项更适合候选项较多的问题。

## 从 Python 微调

`laya-train` 内部调用 `laya.train.finetune`：

```python
import laya
from laya.train import TrainConfig, finetune

report = finetune("train.jsonl", "english", "./my-checkpoint",
                  TrainConfig(loss="soft-ce", shuffle_options=("choice",)))
print(report["train_items"], report["skipped"], report["calibration"])

agent = laya.load("./my-checkpoint")
```

`TrainConfig()` 包含上表的默认值，还提供命令行未暴露的设置：`amp`、`gradient_checkpointing`（CUDA 默认启用）、校准数据比例（`calib_max=400` 与 `calib_frac=0.1`，取较小者）和 `option_layout`。

返回报告包含 `train_items`、`calibration_items`、`skipped`、`epoch_loss`、拟合的 `temperature`、`temperature_by_options` 以及 `calibration` 报告。自建数据流程时，`train_model` 与 `calibration_records` 分别承担训练和生成校准记录。[中文 API 索引](reference/train.zh-CN.md) 列出了相关入口。

## Notebook 按什么顺序执行

| 步骤 | 环节 | 内容 |
|---|---|---|
| 1 | 环境 | 确认双 T4 均可见且已分配 |
| 2 | 安装 | 安装 `laya`、`transformers`、`datasets` 和训练依赖 |
| 3 | 预处理 | 将 1,200 个案例、6,000 次决策转为带软目标的 token 样本，写入磁盘供两个 DDP 进程读取 |
| 4 | 训练 | 使用 `torchrun --nproc_per_node=2` 运行 `train_ddp.py`，训练 4 轮 |
| 5 | 校准 | 最后一轮后，在训练前留出的数据上按类型拟合温度 |
| 6 | 评估 | 用微调模型回答官方 test 集：400 个案例、2,000 次决策，并记录每个案例的延迟 |
| 7 | 指标 | 准确率、软准确率、Brier、ECE、score MAE、误差不超过一级的比例、KL/TV、延迟分位数；与 Jev 和教师参考上限比较 |
| 8 | 发布 | 可选：根据实际成绩生成模型卡，将目录上传 Hub |
| 9 | 报告 | 输出 `benchmark_report.json`，包含指标表和各工作流准确率 |

Kaggle 设置：加速器选择 `GPU T4 x2`，网络选择 `On`。输出目录为 `/kaggle/working/laya_finetuned_typed_decisions`。

## 训练配方

Notebook 中的 RLCD 使用基准的 gold 概率分布训练。每个样本都携带教师对各候选项的概率，两部分损失均使用这个目标：

- 在带噪声的 logits 投影采样上计算策略梯度项：类似 GRPO，每个样本采样 4 次，探索噪声从 0.4 退火到 0.1；奖励采用适当评分规则，球面评分权重为 0.75，排序概率评分权重为 1.0。
- 对同一个目标分布计算全权重软交叉熵。

Notebook 针对 16 GB 显卡采用：

| 项目 | 设置 |
|---|---|
| 训练轮数 | 4 |
| 有效批量 | 64：micro-batch 8 × 2 GPU × 梯度累积 4 |
| 学习率 | 编码器 2.5e-5、决策头 1e-4；AdamW、余弦调度 |
| 显存控制 | fp16 autocast，编码器和决策头梯度检查点，梯度范数裁剪 1.0 |
| 序列预算 | `max_len=1024`、`head_max_len=256`、`max_tokens_per_batch=4096` |

原文的双 T4 示例耗时：6,000 次决策约 4–6 分钟；约 30,000 个问题训练 4 轮约 4–5 小时。这些时间属于该实验环境，不能直接当作 233 的耗时估计。

替换为自己的数据时，修改两个 `load_dataset` 调用，并保持行结构：`state`、`questions`、`gold`。预处理器将案例转为训练样本。可使用 `choice`、`score`、`noul` 三种问题类型，凡是能表示为这些类型的状态决策，都可以按此流程训练。

## 校准是训练流程的一部分

复制训练流程时，校准容易被遗漏；一旦按置信度决定是否放行，它就是关键步骤。

Notebook 在向各训练进程分片之前，从数据中留出最多 400 个、或 10% 的校准样本；使用固定种子，所有进程得到相同切分。如果用参与训练的样本拟合温度，测到的是训练拟合程度：模型已接近确定且正确，优化器缺少调整信号，可能得到退化的缩放值。

最后一轮结束后，rank 0 用 LBFGS 对 log-temperature 进行优化，按 `choice/score/noul` 各拟合一个温度，限制在 `[0.1, 10]`。样本不足 10 个时使用 1.0；拟合异常时使用 1.2。温度写入 `rl_agent_config.json` 的 `temperature`，同时移除继承的 `temperature_by_options`，因为旧的分桶温度在推理时优先使用，会覆盖新校准结果。

温度缩放不会改变概率最大的选项，因此不会改变分类准确率；它改变的是置信度。原文指出发布的 checkpoint 可能过度自信，因此应先校准，再使用阈值，并在留出数据上验证改善。配置持久化回归检查无需下载或训练：

```bash
python tests/test_calibration_persistence.py
```

## 信任模型前先评估

Notebook 在完整官方测试集上评估：400 个案例、2,000 次决策，覆盖代理轨迹可观测性、客户服务、发票处理和安全事件四个工作流。

计算指标包括准确率、软准确率、Brier、ECE（通过 `laya.common.ece_score`）、score MAE、误差不超过一级的比例和延迟分位数。参考表为：

| 模型 | 类型 | 准确率 | ECE |
|---|---|---|---|
| TypeSafe Jev 1.13.0 | 通用 | 0.727 | 0.144 |
| ModernBERT-base（149M） | 专用 | 0.646 | 0.179 |
| 教师自身一致性 | 参考上限 | 0.735 | — |
| Laya 发布 checkpoint | 微调 | 0.766 | — |

你自己的 Laya 成绩应由实际运行计算，notebook 会重建该行。值得保留的两个做法：在留出数据中覆盖关注的语言或工作流；同时报告准确率和校准结果，因为训练目标可能是概率分布。可以在项目 [Discussions](https://github.com/NandhaKishorM/laya/discussions) 分享结果；基准与限制见仓库根目录 `BENCHMARKS.md`。

## 上传 Hub

发布单元是可选的最后一步：

1. 在 Kaggle 的 Add-ons → Secrets 中配置有写权限的 `HF_TOKEN`。缺少时，单元会报错并给出说明。
2. 设置目标仓库。原示例默认使用项目自己的命名空间，运行前应更换。
3. 运行发布单元：根据本次指标生成模型卡，上传 `model.safetensors`、`encoder/`、`tokenizer/`、`rl_agent_config.json`、模型卡和基准报告。

结果使用普通加载接口：

```python
import laya

agent = laya.load("your-org/your-checkpoint")
result = agent.predict(state, questions)
```

每轮重写的 `checkpoint_latest/` 保留最近完成的一轮 checkpoint，减少超时或 OOM 时丢失的进度。

## 需要关注的问题

- 标签质量决定训练效果。RLCD 模仿教师给出的概率分布，应先收集或同时收集教师置信度，并考虑教师质量的限制。
- 校准切分较小：最多 400 个或 10%，足以拟合少量温度参数，但不能代替独立验证集。
- 标签应能表达为有限选项、等级或真假概率。候选项过多会降低置信度选择效果（[#394](https://github.com/NandhaKishorM/laya/issues/394)）；强制选择问题中的否定措辞可能让模型更受问题文本而非输入状态影响（[#377](https://github.com/NandhaKishorM/laya/issues/377)）。
- 分发完整配置和权重。若复制配置时保留本应删除的旧 `temperature_by_options`，新校准会失效。

## 当前仓库实现补充（非原文翻译）

当前 `laya/train_cli.py` 还提供 `--eval` / `--eval-data`，用于训练前后对比；`--target-error` 和 `--min-abstain-n` 用于拟合弃权阈值。`laya/train.py` 会检查评估输入与训练/校准输入是否重叠。可通过 `python -m laya.train_cli --help` 查看当前参数。

`--target-error 0.02` 不能自动保证数学本地求解正确率达到 98%：它对应训练模块的弃权校准目标，而数学路由还需要单独核算被放行题目的本地实际表现。
