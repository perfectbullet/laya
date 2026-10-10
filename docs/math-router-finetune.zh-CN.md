# MongoDB 数学路由微调说明

本文解释本项目数学路由的数据与标签，不是英文指南的翻译。先读 [中文微调指南](finetune.zh-CN.md)，再结合本说明理解数据准备。部署条件见仓库根目录的 `DEPLOYMENT_REPORT_2026-10-09_CORRECTION.md`。

当前测试环境固定使用全量三分类 `final-all663-epochs20`，**只评价题目难度标签分类是否准确**。接口参数和旧版本迁移见 [当前测试环境使用说明](math-difficulty-test-api.zh-CN.md)。以下 capability-v1、local/online、解题答错率及路由覆盖率内容是历史实验记录，不是当前难度分类器的训练标签或验收标准。

## 当前评估目标：只判断题目难度分类是否准确

输入为原始题面，目标标签来自 `questions.difficulty`，映射为 simple（简单）、medium（中等）、difficult（困难＋压轴）。解题模型是否答对与分类器的标签正确性是两件事；简单题被解题模型答错，不应据此改为困难标签。训练/测试不向模型输入人工难度字段或答案。

| 指标 | 分组五折测试 | 最终全量模型训练题回放 |
|---|---:|---:|
| 难度标签准确率 | 77.38% | 90.95% |
| 宏平均召回率 | 62.13% | 93.07% |
| 简单精确率 / 召回率 / F1 | 26.39% / 38.00% / 31.15% | 65.33% / 98.00% / 78.40% |
| 中等精确率 / 召回率 / F1 | 55.56% / 62.07% / 58.63% | 80.00% / 91.03% / 85.16% |
| 困难精确率 / 召回率 / F1 | 94.17% / 86.32% / 90.08% | 99.76% / 90.17% / 94.73% |

精确率表示被预测为某类的题中，有多少与人工标签一致；召回率表示实际属于某类的题中，有多少被识别；F1 综合这两项。五折测试的简单精确率仍低，说明不能只凭整体准确率认为三类都判得很好。最终回放虽然改善，但用的是训练题；最终模型尚无全新题独立测试成绩。两列不是同口径模型优劣对照，也不是数学解题正确率。

固定本版本作为测试环境，后续采集未参与训练的新题人工难度标签，报告准确率、每类精确率/召回率/F1 和混淆矩阵；若使用类别概率门槛，应另外做独立分类置信度校准。模型正确性评价不再以 local 答错率、online 风险召回或 98% 解题正确率为条件。历史报告文件中保留的 `policies` 字段仅用于审计早期路由分析，不作为当前分类验收指标。

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

部署报告显示，233 使用支持 V100 的 CUDA 12.6 PyTorch 环境，模型已离线缓存。2026-10-10 已实测 230 驱动修复成功，RTX 4080 16 GB 的基础 CUDA 正反向检查与 multilingual 服务预测均通过；当前优先考虑 230 训练。实际训练前仍需核查可用显存、磁盘、题面 token 预算和训练峰值显存。

计划的数据流程是：只读查询 MongoDB → 生成可追溯标签与题目切分 → 导出 JSONL → dry-run 检查 → 比较冻结编码器和全参数微调 → 校准 → 评估 → 决定是否部署。

训练产物应写入独立目录，例如 `/data/metahuman_work/laya-finetunes/<run-id>`，保留任务定义原文、哈希、切分清单与标签版本。以下数据已导出；2026-10-10 已完成 230 上的一次冻结编码器短试跑，见末尾。

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

注意：当前 `laya-train` 会从 `--data` 内随机留出校准集。本项目新增的 `scripts/train_math_route.py` 显式使用上述独立校准集，不调用默认随机切分。

## 三倍采样与显式校准包装脚本

仅复制训练集的 online 行三次，不复制 local，不改变校准和测试文件。原始快照保持不变；派生快照保存原始 manifest、重复倍数和新文件校验和。脚本校验原始文件、题面/标签与审计记录的一致性，以及同一折三个集合的分组隔离，拒绝覆盖输出目录。

```bash
python scripts/train_math_route.py prepare \
  --source data/math-router/capability-v1-20261010 \
  --out data/math-router/capability-v1-online3x-20261010 \
  --online-repeat 3
python scripts/test_train_math_route.py
```

每折派生训练集为 168 行（132 local、36 online），仍只有 144 道不同题目。校准、测试各 48 行（44 local、4 online），与原始文件逐字节一致。对照实验可指定 `--online-repeat 1` 导出另一目录。

230 独立工作目录为 `/data/metahuman_work/laya-math-training/20261010/`，已同步脚本和派生数据；没有同步 `.env`、MongoDB 密码或模型配置密钥。以下命令在 230 的 `/data/metahuman_work/laya` 执行；再次训练时请更换 `--out`，不要覆盖短试跑产物：

```bash
PYTHONPATH=/data/metahuman_work/laya HF_HUB_OFFLINE=1 \
  /data/qianyong/miniconda3/envs/laya/bin/python \
  /data/metahuman_work/laya-math-training/20261010/scripts/train_math_route.py train \
  --data /data/metahuman_work/laya-math-training/20261010/data \
  --base /data/metahuman_work/models/laya/multilingual \
  --out /data/metahuman_work/laya-math-training/20261010/fold-0-frozen-next \
  --fold 0 --epochs 4 --micro-batch 2 --grad-accum 8
```

加 `--dry-run` 只检查数据校验和及全部 240 道题的 tokenizer 预算，不加载模型权重或训练；发现题面截断则报错，不静默训练截断题。默认冻结编码器、soft-ce 损失、随机候选顺序；加 `--full` 才开启全参数训练。校准仅使用 `calibration.jsonl` 拟合温度，`test.jsonl` 不参与温度拟合。

保存训练产物后，可使用同一 `train` 子命令，加 `--evaluate-only --runtime`，把 `--base` 和 `--out` 都指向新 checkpoint 目录。此操作不训练，输出独立的 `routing-runtime-evaluation.json`，含校准/测试每题的题面哈希、真实标签与 `P(local)`。它直接使用 `laya.Agent.predict`，与服务推理精度、单题调用及概率舍入保持一致。只在校准集选择历史安全标签比例至少 98%、至少放行 10 题的最高覆盖率阈值；没有合格门槛则全部 online。测试集只应用已选门槛，不能再调阈值。只加 `--evaluate-only` 时产生的 `routing-evaluation.json` 是 FP32 训练路径诊断，不能代替实际服务回放。

此门槛只是小样本开发诊断，不是证明真实解题正确率达到 98%；不能自动用于生产。报告中的默认 `TrainConfig.target_error` 未被使用，路由门槛按上述独立回放选择，也不继承零样本的 `P(simple)>=0.70`。

## 230 短试跑实测（2026-10-10）

实测时 230 的 8000 端口未监听；GPU 已用约 831 MiB、空闲约 15,115 MiB。未执行启停服务或修改原始 checkpoint。

- 全量 240 道题：最长题面 255 tokens，完整序列最长 332 tokens；`max_len=1024`、`head_max_len=256`，截断 0 道。
- fold-0，冻结编码器、1 epoch、micro-batch 2、累积 8、head_lr=1e-4，平均损失约 0.7201。
- PyTorch 峰值 allocated 1,489.63 MiB（1.45 GiB），reserved 1,568 MiB（1.53 GiB）。这不是整卡占用，也不代表全参数训练峰值。
- 训练及前后测试/校准计算约 2.06 秒，不含模型加载、tokenizer 检查和保存。默认冻结特征提取器的一轮试跑仅约 11 次优化器更新。
- 测试集 48 题，默认最高概率分类准确率训练前后均为 50%；校准温度达到上限 5.0，校准数据只有 48 条。不可据此认为路由已训练成功。
- 保存后重新加载 checkpoint，默认 `P(local)>=0.5` 放行 24 题，其中 2 道历史风险题被误放行。
- 校准集选出约 0.544563 的开发门槛：校准放行 10/48、历史风险误放行 0；测试放行 8/48（16.67%）、历史风险误放行 0。8 道题的观测不能支撑未知题 98% 的正确率结论。

服务器产物目录：`/data/metahuman_work/laya-math-training/20261010/fold-0-frozen-smoke/`，含独立 checkpoint、任务定义、`report.json` 和 `routing-evaluation.json`。本地已取回报告及日志到 `data/math-router/capability-v1-online3x-20261010/smoke-results/`（Git 忽略），模型权重没有取回或提交。

短试跑之后的完整五折对照见下文。233 生产服务始终不变。

## 原始模型位置与微调对象

本次微调的是 **Laya multilingual 路由决策模型**，不是本地解题模型，也不是 DeepSeek 解题模型；没有使用 `typed-decisions` 作为基座。各折均从同一个原始 checkpoint 重新加载，不从上次短试跑或其他折的训练结果继续训练。

- 230 原始 checkpoint：`/data/metahuman_work/models/laya/multilingual/`。其中 `model.safetensors` 是原始权重，`rl_agent_config.json` 是任务头/温度等配置，`encoder/` 和 `tokenizer/` 是编码器配置与分词文件。
- 核实来源：`convaiinnovations/laya` 仓库的 `multilingual` 子目录。原始权重与 230 的 Hugging Face 缓存 revision `7b928d828b7b0e022f929d9bd2e44165aa270148` 中的权重 SHA-256 一致。
- 对应缓存路径：`/home/zenking/.cache/huggingface/hub/models--convaiinnovations--laya/snapshots/7b928d828b7b0e022f929d9bd2e44165aa270148/multilingual/`。
- 原始权重 SHA-256：`9d628fd971b700382ac6f65920a86f149777b2e748e0c955fb3b19695aa8f204`。
- 原始配置 SHA-256：`25061739243b617ad88d1219ba6f8a9c86c5881ca28df024fa2d9b3b2fcc30c6`。

`encoder/config.json` 显示编码器类型为 ModernBERT（22 层、隐藏维度 768）；加载的是 Laya 已训练过的完整 multilingual 权重，不是另行下载一个空白 ModernBERT 模型来训练。训练报告保存基座路径及权重/配置哈希，五折脚本在结束时再次核对原始文件未改变。

**冻结编码器**确实是让编码器参数不参与更新：`requires_grad=False`，编码器保持 eval 模式以避免 dropout 噪声，只训练编码器以外的决策网络参数。编码器仍会读取题面并计算特征，并非不运行编码器。微调模型随后再用独立校准集拟合温度；温度拟合不更新编码器。`--full` 才会开启编码器参数更新，本轮没有使用。

## 完整五折对照的运行方式

新增 `scripts/benchmark_math_route.py` 顺序执行两个方案、每个方案五折，保存各折 checkpoint、日志和汇总；训练默认冻结编码器。两个方案使用同一题面、标签、固定切分、基座、随机种子和 4 epochs。三倍采样增加训练行数，因此也增加优化器更新次数；本轮比较的是两种实际训练方案，并非固定更新次数的纯权重消融实验。

```bash
python scripts/train_math_route.py prepare \
  --source data/math-router/capability-v1-20261010 \
  --out data/math-router/capability-v1-online1x-20261010 --online-repeat 1
```

230 上执行（再次运行需更换输出目录）：

```bash
PYTHONPATH=/data/metahuman_work/laya HF_HUB_OFFLINE=1 \
  /data/qianyong/miniconda3/envs/laya/bin/python -u \
  /data/metahuman_work/laya-math-training/20261010/scripts/benchmark_math_route.py \
  --data-1x /data/metahuman_work/laya-math-training/20261010/data-online1x \
  --data-3x /data/metahuman_work/laya-math-training/20261010/data \
  --base /data/metahuman_work/models/laya/multilingual \
  --out /data/metahuman_work/laya-math-training/20261010/frozen-fivefold-v1 --epochs 4
```

每折只用自己的校准集选择阈值，五折测试汇总时每道题恰好出现一次。没有合格阈值的折全部走 online。`--baseline-only` 可对原始权重做相同五折阈值回放（不训练），需单独输出目录。测试结果只用于比较方案，不用来挑选“测试成绩最好的一折”部署。

230 替换模型的接口测试使用 `scripts/check_math_route_http.py`：通过 `Router(models={"multilingual": checkpoint_path})` 为临时测试进程指定新权重，不覆盖磁盘上的原始模型。该脚本拒绝占用中的端口，短暂监听 `127.0.0.1:8000`，用实际 HTTP 请求回放一折测试题，检查无截断、概率与离线回放一致，最后关闭自己创建的测试进程。233 服务与其它进程不受影响。

### 为什么需要服务路径回放

第一次 HTTP 检查发现，训练模块的 `calibration_records` 使用 FP32，而 230 的 `Agent` 依据 checkpoint 的 `amp_dtype=bf16` 使用 CUDA BF16 autocast。初次 online1x/fold-0 的 48 道 HTTP 测试中，33 道的 P(local) 与 FP32 回放差异超过 0.001，最大约 0.00514，默认放行数量也不同。这不是可以忽略的接口舍入问题。因此保留原始 FP32 报告，并重新使用实际 `Agent.predict` 对校准集和测试集回放；不通过放宽检查来掩盖差异。

`scripts/replay_math_route_runtime.py` 为原始基线及两个采样方案重做五折服务路径回放，结果保存在各折的 `routing-runtime-evaluation.json` 与训练根目录的 `summary-runtime.json`。服务路径阈值重新在各折校准集选择，不借用 FP32 阈值或测试标签。

这里保留训练时在 FP32 校准集拟合的 checkpoint 温度，没有伪称重新做了 BF16 温度拟合。运行时回放重新确定的是路由阈值。所有训练折的温度都触及上限 5.0，本身就提示模型/校准证据不足；未来正式校准也应对齐实际部署精度。233 的 V100 默认可能使用 FP16，不能不回放就直接复用 230 的 BF16 门槛。

### 完整五折的最终结果（实际服务路径）

两个方案各 5 个 checkpoint 已完成，均训练 4 epochs，报告确认编码器参数全部冻结，实际可训练决策网络参数为 14,969,347。十次训练的 PyTorch 峰值 allocated 最大 1,491.16 MiB（约 1.46 GiB）；训练加前后测试/校准计算累计约 40.23 秒，不含各次加载、保存、额外运行时回放及 HTTP 测试。

以下为 230 的 BF16 `Agent.predict` 路径、每折独立校准门槛的测试汇总。测试集合共 240 道不同题目，每道恰好出现一次：

| 方案 | 本地放行 | 本地覆盖率 | 历史风险题误放行 | 放行集合历史安全标签比例 |
|---|---:|---:|---:|---:|
| 原始 multilingual，同一 math_route 任务定义 | 8/240 | 3.33% | 0 | 100%（仅 8 题） |
| 冻结编码器，不重复采样 | 34/240 | 14.17% | 2 | 94.12% |
| 冻结编码器，online 三倍采样 | 35/240 | 14.58% | 2 | 94.29% |

原始基线不是既有 `multilingual + 难度 v3 + P(simple)>=0.70` 生产策略；这里控制任务定义一致，使用训练时的 `math_route: local/online` 提示词来衡量权重变化。因此不能根据此表宣称微调优于既有 v3。

两种微调方案覆盖率相近，历史风险误放行数相同，没有证据支持三倍采样显著更好。原始基线放行 8 题的零误放行也不能证明其未知题安全率达到 98%。表内比例是对 `capability-v1` 历史标签的符合率，不是最终解题正确率：风险题并非每次一定答错，online 也不能被当成必然正确。当前样本属于开发评估，没有运行全新题上的端到端 solver 正确率验证。

若不使用校准门槛、仅按 P(local)>=0.5 放行，原始模型为 123/240、误放行 8；不重复方案为 131/240、误放行 8；三倍方案为 132/240、误放行 8。增加覆盖率并没有解决风险识别。各微调方案的 fold-2 和 fold-3 均未找到满足最少 10 道放行条件的校准门槛，保守退回全部 online。

作为对照，保留的 FP32 诊断是：不重复方案放行 37/240、误放行 2；三倍方案放行 20/240、误放行 1。这个结果与 BF16 服务路径不同，不应继续把“三倍采样更保守”作为接口行为结论。

已在 230 的临时 `127.0.0.1:8000` 服务中依次加载两个方案预先固定的 fold-0 checkpoint，各通过 48 道实际 HTTP 请求检查：health 显示 CUDA、只加载 multilingual、CPU fallback 为 0，题目无截断，概率与运行时回放一致。校准门槛分别为 0.5556 和 0.5351，HTTP 测试放行 7 道和 8 道，均无历史风险误放行。未按测试结果挑选折。两次临时服务随后正常关闭，230 没有留下常驻测试服务；233 未访问或修改。

产物与报告位置：

- 230 十个训练 checkpoint：`/data/metahuman_work/laya-math-training/20261010/frozen-fivefold-v1/online1x/fold-0..4/` 与 `online3x/fold-0..4/`。
- 230 最终汇总：同一根目录的 `summary-runtime.json`；FP32 诊断为 `summary.json`。
- 230 原始模型五折回放：`/data/metahuman_work/laya-math-training/20261010/original-fivefold-v1/`，没有训练原始权重。
- HTTP 通过报告：训练根目录的 `http-runtime-online1x-fold0.json`、`http-runtime-online3x-fold0.json`；初次失败报告单独保留，未覆盖。
- 本地报告：`data/math-router/frozen-fivefold-v1/`、`data/math-router/original-fivefold-v1/`，均被 Git 忽略；没有下载或提交模型权重。

原始模型权重和配置在训练前后哈希一致。当前建议维持 233 既有生产模型，不部署这次冻结基线。后续优先补充更多来自实际本地失败/截断的、彼此独立的风险题，并预留全新测试集；再比较全参数小规模基线与冻结编码器方案。全参数训练、本轮结果部署及生产阈值变更均尚未执行。

## online 风险召回实验：online-risk-v1

新目标是优先识别历史本地失败/截断题，在校准集风险题全部被送到 online 的约束下，尽量少把 local 安全题误送 online。标签仍为 capability-v1 的实际本地表现，不使用人工难度或模型自评分替代标签。

风险检测提示词固定在 `scripts/math_online_risk_questions.json`。派生快照仅替换每条数据的任务定义，不修改题面、真实标签、分组或五折 ID；审计文件保持原样，manifest 记录提示词原文和哈希。候选项为 online/local，但不能把交换选项顺序本身当成效果改善。

路由规则为 `P(online) >= τ` 走 online，等号也走 online。每折在独立校准集选择 `τ = min(该折四道 online 风险题的 P(online))`，这是零漏判条件下允许的最高门槛，可最小化校准集安全题误转在线；概率并列时全部送 online。若校准集没有风险标签，则退回 τ=0、全部 online，不将缺乏证据解读为可靠。测试集不参与 τ 的选择；旧的最少放行 10 题和放行安全比例 98% 规则不再作为此实验的选阈值条件。

评估字段包括 online 召回率 `(风险题总数-漏判数)/风险题总数`、local 误转在线率 `安全题误转数/安全题总数`、风险漏判数和本地覆盖率。没有风险题或安全题时，对应比率为 null，不伪造 100%。每折校准集只含 4 道风险题，校准零漏判不能保证未知题零漏判。

第一轮比较原始 multilingual 回放、普通采样冻结编码器微调、online 三倍采样冻结编码器微调。三倍采样提高风险题的训练曝光，是类别加权的采样实现，不是严格固定优化步数的加权交叉熵消融实验。本轮仍使用原有 soft-ce 损失，没有修改 Laya 公共训练 API，没有实现或声称实现单独的 weighted-CE 损失。

准备数据：

```bash
python scripts/train_math_route.py prepare \
  --source data/math-router/capability-v1-20261010 \
  --out data/math-router/online-risk-v1-online1x \
  --online-repeat 1 --questions-file scripts/math_online_risk_questions.json
python scripts/train_math_route.py prepare \
  --source data/math-router/capability-v1-20261010 \
  --out data/math-router/online-risk-v1-online3x \
  --online-repeat 3 --questions-file scripts/math_online_risk_questions.json
```

230 工作根目录为 `/data/metahuman_work/laya-math-training/online-risk-v1/`，数据分别在 `data-online1x/` 和 `data-online3x/`；基座仍是 `/data/metahuman_work/models/laya/multilingual/`。

在 230 使用相同 Conda 环境和 `PYTHONPATH=/data/metahuman_work/laya HF_HUB_OFFLINE=1`，执行训练包装脚本：

```bash
python scripts/benchmark_math_route.py \
  --data-1x /data/metahuman_work/laya-math-training/online-risk-v1/data-online1x \
  --data-3x /data/metahuman_work/laya-math-training/online-risk-v1/data-online3x \
  --base /data/metahuman_work/models/laya/multilingual \
  --out /data/metahuman_work/laya-math-training/online-risk-v1/frozen \
  --runtime --objective online-recall --epochs 4
```

上述 `scripts/` 为工作根目录中同步的脚本目录，不是原始项目的脚本路径。原始基线用同样参数、另选输出目录 `original/` 并添加 `--baseline-only`，不执行训练。报告直接使用 BF16 `Agent.predict` 返回的 `P(online)`，而不是用另一个精度或人工难度字段推断概率。最终结果仍属于开发评估，不能从多轮调参的数据推断未知题正确率。

### online-risk-v1 实测结果

原始模型五折回放、两个采样方案各五折冻结编码器训练（4 epochs）均已完成。门槛仅用每折校准集的四道风险题选择；所有折校准召回率为 100%。测试汇总包含 20 道 online 风险题和 220 道 local 历史安全题：

| 方案（相同风险检测提示词） | 风险召回/20 | online 召回率 | 风险漏判 | local 误转在线/220 | local 误转在线率 | 本地放行/240 |
|---|---:|---:|---:|---:|---:|---:|
| 原始 multilingual | 15 | 75% | 5 | 132 | 60.00% | 93 |
| 冻结编码器，普通采样 | 15 | 75% | 5 | 130 | 59.09% | 95 |
| 冻结编码器，online 三倍采样 | 15 | 75% | 5 | 135 | 61.36% | 90 |

普通采样仅比原始模型减少两道安全题误转，三倍采样反而增加三道，三者风险召回率没有改善。不能据此宣称微调有效，也不能认为风险题已全部覆盖。若直接使用 P(online)>=0.5，三个方案在本轮测试上风险召回率均为 0%，说明默认分类门槛完全不适合这个风险召回任务；不能只看约 90% 的整体分类准确率。

每折门槛不同，普通采样 P(online) 门槛为 0.042、0.0422、0.071、0.0698、0.063；三倍采样为 0.0451、0.0403、0.0583、0.0851、0.0637。这些是开发校准门槛，不是可直接用于生产的固定风险概率。温度仍由独立校准集的 FP32 logits 拟合，而路由门槛与测试回放均使用 BF16 单题运行时输出；没有声称完成 BF16 logits 的温度重新拟合。

十次训练峰值 PyTorch allocated 最大约 1,496.71 MiB（1.46 GiB），基座权重与配置训练前后哈希一致。两个方案预先固定的 fold-0 checkpoint 已分别在临时 localhost:8000 服务中通过 48 道实际 HTTP 请求：P(online) 门槛为 0.042 和 0.0451，均召回该折测试的四道风险题，但也将 38/44 道安全题误送在线。题目无截断、概率及门槛决策与回放一致、CPU fallback 为 0。测试进程均已关闭，不触碰 233 服务。

230 产物：`/data/metahuman_work/laya-math-training/online-risk-v1/frozen/` 内的各折模型、`summary.json` 和 `http-online1x-fold0.json` / `http-online3x-fold0.json`；原始基线在工作根目录的 `original/summary.json`。轻量报告与日志取回到本地 `data/math-router/online-risk-v1-results/`，不下载模型权重，Git 忽略。

本轮结论是新目标和实验机制已实现，但尚未达到高风险召回、低误转在线的业务目标。新提示词、候选顺序和门槛规则同时变化，因此与旧 local-safe 实验的差异不能单独归因于提示词。仍需更多独立的失败/截断样本及全新测试集；后续可比较严格加权交叉熵和全参数微调，而不是只调整概率门槛。本轮未实现严格加权损失、未执行全参数训练、未部署新模型。

## 全部 20 道 online 参与每折训练：all-online-v1

按用户指定的新协议，每折全部 20 道独立 online 题用于训练，不再分配独立 online 验证或测试题。local 题沿用原来的分组和切分：每折 132 道训练、44 道校准、44 道测试。普通采样训练 152 行；online 三倍采样训练 192 行（132 local + 60 online，后者仍是同样 20 道题）。每模型 4 epochs，仍冻结编码器；两个方案各训练五折。

准备数据时添加 `--all-online-train`：

```bash
python scripts/train_math_route.py prepare \
  --source data/math-router/capability-v1-20261010 \
  --out data/math-router/all-online-v1-online1x --online-repeat 1 \
  --questions-file scripts/math_online_risk_questions.json --all-online-train
python scripts/train_math_route.py prepare \
  --source data/math-router/capability-v1-20261010 \
  --out data/math-router/all-online-v1-online3x --online-repeat 3 \
  --questions-file scripts/math_online_risk_questions.json --all-online-train
```

manifest 明确标记 `protocol=all-online-in-train` 和 `riskCalibrationIsTrainingReplay=true`。原始 sourceManifest 只记录来源切分，不代表派生快照仍有独立 online 测试题。脚本只允许训练/校准之间、且双方标签都为 online 的协议内重叠；local 重叠和训练/测试重叠仍会报错，不全局关闭数据泄漏检查。

`calibration.jsonl` 中包含独立的 44 道 local 校准题和 20 道训练过的 online 风险参考题，共 64 条。这种混合参考集用于拟合温度和选门槛，**不是独立风险校准集**。门槛设为已训练风险题的最小 P(online)，保证这 20 道已知题被送到 online；该覆盖率是选门槛的构造结果，不能据此证明模型学会了识别未知风险。

`test.jsonl` 只包含每折独立的 44 道 local 题。五折汇总时共 220 道不同 local 测试题，能衡量安全题误转在线率；独立风险召回率明确为 null，而不是 100%。报告另列 `trainingRiskReplaySelected` 和 `trainingRiskReplayDefault`，分别记录按选定门槛和默认 P(online)>=0.5 对训练风险题的回放。五折重复出现的 20 道风险题不能计作 100 道独立风险样本。

230 工作目录为 `/data/metahuman_work/laya-math-training/all-online-v1/`；训练使用 `scripts/benchmark_math_route.py --runtime --objective online-recall --epochs 4`，数据在 `data-online1x/` 和 `data-online3x/`，输出在 `frozen/`。基座仍是原始 multilingual，每折重新加载，233 服务不变。

### all-online-v1 实测结果

两个方案各五折、每模型 4 epochs 的冻结编码器微调已完成，已核查每折训练集 online 的独立题面集合与完整 20 道风险题集合一致。普通采样为 132 local + 20 online，三倍采样为 132 local + 60 online 训练行，后者不增加独立题目数量。

| 方案 | 已训练 online 题按选定门槛回放 | 默认 0.5 门槛下已训练 online 识别 | 独立 local 测试误转在线/220 | local 误转在线率 | 独立 local 题留在本地 |
|---|---|---|---:|---:|---:|
| 普通采样 | 每折 20/20 | 每折 0/20 | 201 | 91.36% | 19/220 |
| online 三倍采样 | 每折 20/20 | 每折 0/20 | 189 | 85.91% | 31/220 |

选定门槛下 20/20 是根据同样 20 道训练题选门槛的构造结果，不能称为独立 online 测试召回率。测试集只有 local，因此测试报告的风险题数量为 0、onlineRecall=null。三倍采样比普通采样少误转 12 道安全题，但两者都将大部分安全题送到 online，未达到低误转在线目标。不能把高 local 分类准确率或训练题全覆盖解读为路由训练成功。

与此前 online-risk-v1 的结果不能作同口径风险召回比较：此前保留未训练风险测试题，本轮没有。本轮为了覆盖完整 20 道已知风险题，门槛由其中最低风险分数确定，误转安全题较多，不仅是采样比例的影响。

运行时回放为 BF16 单题 `Agent.predict`，温度拟合和门槛选取均使用明确标记的混合参考集（其中 online 题已训练）。原始模型权重与配置训练前后哈希一致，未部署到 233。

服务器 checkpoint：`/data/metahuman_work/laya-math-training/all-online-v1/frozen/online1x/fold-0..4/` 和 `online3x/fold-0..4/`，汇总为 `frozen/summary.json`。本地轻量报告与日志为 `data/math-router/all-online-v1-results/`，数据/权重不提交 Git。

两个方案预先固定的 fold-0 checkpoint 分别通过临时 HTTP 回放：44 道独立 local 测试题，加 20 道已训练 online 题，共 64 次请求；风险回放与 local 独立测试分别记录。检查包括无截断、无 CPU fallback、概率和门槛决策与运行时回放一致，临时测试进程最后关闭。

## 增加至 20 epochs：all-online-v1 对照实验

2026-10-10 按用户要求，在 230 将训练轮数从 4 增加至 20。普通采样和 online 三倍采样各训练五折，每折重新加载原始 multilingual，不从四轮模型续训。与对应四轮报告逐项核查：训练配置仅 `epochs` 不同，数据 manifest 哈希相同，每折独立 local 测试题的题面哈希集合相同。

保持冻结编码器、soft-ce、候选顺序打乱、固定种子、学习率、micro-batch 2、梯度累积 8 和风险检测提示词不变。普通采样每轮 152 行、10 次优化器更新，20 轮共 200 次更新；三倍采样每轮 192 行、12 次更新，共 240 次更新。余弦学习率调度随总更新数延长；本轮比较的是完整训练预算增加，并非保持前四轮学习率轨迹不变的续训实验。

本轮使用 230 上 all-online-v1 已有包装脚本；`benchmark_math_route.py` SHA-256 为 `a3f1f3fbd92ceee7d26a8fc5607846b842ab911bcadff40645efddecf2bdf4f0`，`train_math_route.py` 为 `caf4d1c254c10bfed6bdcf3897687aac4a0ba622c873d52635550a0d1bc41551`。后者早于本地补充解释性元数据的版本，回放报告中的通用“四道风险校准题”文字不适用于此协议；实际计数均为 20 道训练风险题，且明确标记 `riskCalibrationIsTrainingReplay=true`，不能当作独立风险校准。

复现命令（再次运行必须更换输出目录）：

```bash
PYTHONPATH=/data/metahuman_work/laya HF_HUB_OFFLINE=1 \
  /data/qianyong/miniconda3/envs/laya/bin/python -u \
  /data/metahuman_work/laya-math-training/all-online-v1/scripts/benchmark_math_route.py \
  --data-1x /data/metahuman_work/laya-math-training/all-online-v1/data-online1x \
  --data-3x /data/metahuman_work/laya-math-training/all-online-v1/data-online3x \
  --base /data/metahuman_work/models/laya/multilingual \
  --out /data/metahuman_work/laya-math-training/all-online-v1/frozen-epochs20 \
  --runtime --objective online-recall --epochs 20
```

### 实测比较

每折仍以同样 20 道训练风险题的最小 `P(online)` 选门槛，确保已知风险题全覆盖；五折测试汇总只包含 220 道不同 local 题，不包含独立 online 风险题。BF16 单题运行时结果如下：

| 采样方案 | 训练轮数 | 独立 local 误转在线/220 | local 误转在线率 | 独立 local 留在本地/220 |
|---|---:|---:|---:|---:|
| 普通采样 | 4 | 201 | 91.36% | 19（8.64%） |
| 普通采样 | 20 | 153 | 69.55% | 67（30.45%） |
| online 三倍采样 | 4 | 189 | 85.91% | 31（14.09%） |
| online 三倍采样 | 20 | 86 | 39.09% | 134（60.91%） |

普通采样增加轮数后少误转 48 道 local；三倍采样少误转 103 道，误转率下降 46.82 个百分点。三倍采样二十轮在本次开发对照中明显更好，但没有运行多随机种子，也没有新的独立风险测试，不能视为泛化或生产正确率保证。

默认 `P(online)>=0.5` 时，普通采样二十轮的每折训练风险识别仍为 0/20；三倍采样二十轮五折分别为 10/20、8/20、9/20、9/20、10/20，相比四轮全部 0/20 有改善，但仍漏掉部分已知风险。五折重复的是同样 20 道题，不能将其合并为 100 道独立风险样本。选定低门槛后的 20/20 仍是门槛构造结果，而非未知风险召回率。

普通采样五折门槛为 0.1886、0.2056、0.2168、0.2233、0.191；三倍采样为 0.0908、0.1373、0.0754、0.1、0.1574，不应挑选测试效果最好的一折或直接复用其中某个门槛到生产。三倍采样各折第一轮平均损失约 0.629–0.651，最终约 0.360–0.384，说明额外训练预算确实降低了训练损失；不能单凭损失下降认定泛化有效。

温度仍在 FP32 的混合参考集拟合（44 道独立 local 加 20 道训练 online）；随后在 BF16 运行时输出上选阈值、评估。增加轮数没有解决训练风险参与温度拟合、缺少独立风险测试、校准精度与服务精度不一致等既有局限。测试报告的 `onlineRecall` 仍为 null，且题目此前用于多轮开发实验；正式宣称 98% 解题正确率需要新的独立题集和实际解题评估。

十次训练的 PyTorch 峰值 allocated 最大 1,497.86 MiB（约 1.46 GiB）；训练及前后 FP32 评估耗时累计约 184.58 秒，不含加载、保存、运行时回放和 HTTP 测试。全部 240 道题无输入截断。两个预先固定的 fold-0 checkpoint 各执行 64 次实际 HTTP 请求并通过检查，CPU fallback 为 0、概率和门槛决策与运行时回放一致，临时进程均已关闭。原始权重和配置哈希未变，233 生产服务未访问、未修改。

230 checkpoint 和汇总在 `/data/metahuman_work/laya-math-training/all-online-v1/frozen-epochs20/`；本地评估报告在 `data/math-router/all-online-v1-epochs20-results/summary.json`。本轮未部署模型，下一步应优先补充独立风险校准/测试题，并对照全参数微调，而不是仅凭已知题覆盖部署。

## 第二版：题面难度三分类（difficulty-threeclass-v1）

按用户接受暂不保证 98% 解题正确率后的新目标，训练任务改为 `math_difficulty: simple/medium/difficult`。标签来自 MongoDB `questions.difficulty`，将“压轴”并入“困难”。模型只输入原始题面及固定任务说明，不输入难度元数据、参考答案、历史模型回答或评估结果。脚本为 `scripts/train_math_difficulty.py`，权重无关检查为 `python scripts/test_train_math_difficulty.py`。

2026-10-10 数据快照共有 665 道：简单 50、中等 145、困难 466、压轴 4。正式本地评估仍为 250 道、750 次，均对应 `nvidia/Qwen3.6-35B-A3B-NVFP4`，评估版本 `evaluator-v1`；新增题没有正式本地答题结果，不能计作本地正确。按已判定推理统计，简单错误 1/149（0.67%，另有一次 review）、中等错误 18/428（4.21%，另有七次 review）。历史答错率不是未知题正确率保证。

首次基线回放在 fold-0 因题面截断而停止，尚未训练出模型。使用原始 tokenizer、固定三分类提示词以及 `max_len=1024`、`head_max_len=256` 检查全部 665 道后，确定只有两道题超出当前题面预算 871 tokens：

| 排除题目 ID | 题面 tokens | 丢弃 tokens | 内容 |
|---|---:|---:|---|
| `ZP-MATH-5_4_27` | 945 | 74 | 企业研发投入与销售收入的回归分析 |
| `ZP-MATH-5_7_34` | 968 | 97 | 最大似然估计与数列求和 |

按用户要求只从此实验数据中排除这两道，不删除 MongoDB 原始题目、不改写题面、不扩大 token 预算。新快照保留 `excluded.jsonl` 和 manifest 排除记录；重新执行固定种子的分组五折切分，同一规范化题面的重复题仍在同一桶内。未过滤快照和失败日志保留，后续训练仍拒绝新的截断，不静默丢弃更多题。

```bash
python scripts/train_math_difficulty.py export \
  --out data/math-router/difficulty-threeclass-v1-filtered \
  --exclude-question-id ZP-MATH-5_4_27 \
  --exclude-question-id ZP-MATH-5_7_34
```

过滤后共 663 道：简单 50、中等 145、困难 468。每折原始训练 397–398 道，校准与测试各 132–133 道，三个集合互不重叠。仅训练集按三类均衡重复采样扩为 840–843 行（每类 280–281 行），不产生新的独立题；校准、测试保持原始类别分布。这是首轮冻结编码器基线，20 epochs、soft-ce、micro-batch 2、梯度累积 8、head_lr=1e-4、固定种子、随机候选顺序；不是全参数训练，也不是固定更新数的纯采样消融。

```bash
PYTHONPATH=/data/metahuman_work/laya HF_HUB_OFFLINE=1 \
  /data/qianyong/miniconda3/envs/laya/bin/python -u \
  /data/metahuman_work/laya-math-training/difficulty-threeclass-v1/scripts/train_math_difficulty.py benchmark \
  --data /data/metahuman_work/laya-math-training/difficulty-threeclass-v1/data-filtered \
  --base /data/metahuman_work/models/laya/multilingual \
  --out /data/metahuman_work/laya-math-training/difficulty-threeclass-v1/frozen-epochs20-filtered \
  --epochs 20
```

每折比较原始 multilingual 与微调模型的实际 `Agent.predict` 三分类结果。微调权重保存后，使用单题运行时的原始 logits，仅在独立校准集拟合温度，再加载持久化配置进行测试；不再采用之前实验的 FP32 训练路径温度拟合。按最高概率类别固定比较“仅简单走 local”和“简单＋中等走 local”两个规则，不继承旧模型的 0.7 或 0.0908 门槛。

路由评估分别报告覆盖率、被放行且有历史评估的题数、被放行但未评估的题数、已判定推理错误率和 review 次数。未评估题不进入答错率分母；不将历史推理错误率当作在线兜底后的端到端解题正确率。250 条记录带有截图路径，不等于题面都依赖图片，但题面是否缺少图形条件仍需人工审查；此轮不读取图片。模型仍在开发阶段，不自动部署到当前 230 或 233 服务。

### 过滤后实测结果（2026-10-10）

663 道题的分组五折、每折 20 轮冻结编码器训练已完成。所有保留题完整输入最长 972 tokens，无题面截断；两个超长题的原始题库记录保留，仅在本轮实验快照排除。已核查五折测试题 ID 恰好覆盖 663 道、各一次，且规范化题面在每折训练/校准/测试之间不重叠。基座原始权重和配置哈希保持不变。

| 指标 | 相同三分类提示词的未微调基线 | 三分类微调 |
|---|---:|---:|
| 测试准确率 | 13.57% | 77.38% |
| 宏平均召回率（平衡准确率） | 33.21% | 62.13% |
| 简单召回率 | 90.00% | 38.00% |
| 中等召回率 | 0.00% | 62.07% |
| 困难召回率 | 9.62% | 86.32% |

这里的未微调基线是原始 multilingual 对新三分类提示词的最高概率分类，不是生产 difficulty-v3 二分类加 0.7 门槛。五折微调测试准确率依次为 77.44%、73.48%、75.94%、77.27%、82.71%。由于困难类别占比高，“全部预测困难”的准确率也有 70.59%，不能只看微调前后整体准确率增幅。

微调后的混淆计数如下；简单、中等类别的界限仍不理想，预测简单的 72 道中实际简单只有 19 道，不能把“预测简单”当作“历史安全”标签。

| 原始难度 | 预测简单 | 预测中等 | 预测困难 |
|---|---:|---:|---:|
| 简单（50） | 19 | 27 | 4 |
| 中等（145） | 34 | 90 | 21 |
| 困难（468） | 19 | 45 | 404 |

两个固定路由策略在微调后五折测试结果上的比较：

| 本地放行规则 | 放行/663 | 覆盖率 | 有历史评估的放行题 | 无评估的放行题 | 已判定推理错误率 | 待审核推理 |
|---|---:|---:|---:|---:|---:|---:|
| 仅预测简单 | 72 | 10.86% | 67 | 5 | 10/198＝5.05% | 3 |
| 预测简单或中等 | 234 | 35.29% | 215 | 19 | 26/633＝4.11% | 12 |

前者有 7 道、后者有 20 道放行题曾至少一次本地答错。第二种策略在此历史子集的错误率更低，不代表它普遍比第一种更安全：两个放行集合不同、分母不同，模型也会把部分困难题错判简单。全部预测结果包含尚未评估的新增题，它们不进入错误率分母；review 不计作正确或错误。没有重新运行解题模型，也没有验证在线兜底后的端到端正确率。

原始三分类基线的“简单＋中等”覆盖率为 90.65%，被放行且有评估的题为 226 道，已判定推理错误率 28/667＝4.20%。因此本次微调确实提高了难度标签分类，但该规则的历史作答错误率只从 4.20% 变为 4.11%，同时覆盖率明显下降；不能宣称业务路由安全性已明显提升。两种难度路由规则可作为新的开发实验，仍需新增本地推理和独立题集验证。

实际校准使用保存后的 FP16 权重、BF16 单题 `Agent` logits，五折报告的 `calibrationDtype` 均为 `torch.bfloat16`。训练阶段峰值 PyTorch allocated 最大 1,552.05 MiB（约 1.52 GiB）；累计训练约 465.04 秒，不含加载、保存、基线与最终回放、温度拟合等阶段。230 原有 8000 服务健康、CUDA 正常、CPU fallback 为 0；本轮训练进程已退出，没有替换当前服务或访问 233。

230 产物：`/data/metahuman_work/laya-math-training/difficulty-threeclass-v1/frozen-epochs20-filtered/fold-0..4/`，汇总 `summary.json`。本地仅保存报告和日志：`data/math-router/difficulty-threeclass-v1-filtered-results/`。后续若部署，应预先固定模型及路由规则，不按测试成绩挑选最好的一折；未知题输入超长时应明确兜底处理，不依赖模型读取截断题面。

## 三分类最终模型：全部 663 道题训练

按用户要求，固定已有参数，用过滤后全部 663 道题训练最终模型：简单 50、中等 145、困难 468。仍从原始 multilingual 加载，而不是续训或选取某折权重。冻结编码器、soft-ce、20 epochs、micro-batch 2、梯度累积 8、head_lr=1e-4、seed=20261010、候选顺序打乱、max_len=1024、head_max_len=256 均不变。三类均衡重复采样每轮 1,404 行（各 468 行），20 轮共 1,760 次优化器更新；原始不同题目数仍为 663，重复采样不创造新题。

```bash
PYTHONPATH=/data/metahuman_work/laya HF_HUB_OFFLINE=1 \
  /data/qianyong/miniconda3/envs/laya/bin/python -u \
  /data/metahuman_work/laya-math-training/difficulty-threeclass-v1/scripts/train_math_difficulty.py final \
  --data /data/metahuman_work/laya-math-training/difficulty-threeclass-v1/data-filtered \
  --base /data/metahuman_work/models/laya/multilingual \
  --out /data/metahuman_work/laya-math-training/difficulty-threeclass-v1/final-all663-epochs20 \
  --epochs 20
```

全量训练没有剩余独立校准/测试题，报告明确标记 `protocol=all-data-final`、`independentEvaluationAvailable=false`。原始模型与新模型的全量回放分别记录为 `baselineTrainingReplay` 和 `trainingReplay`，不使用独立测试字段名。五折结果用于描述此前训练方案的开发表现，不能冒充最终模型的独立评估。

本轮不在训练题上拟合温度，不沿用任何一折的温度或概率门槛。保存 `temperature=[1,1,1]`、清除旧分桶温度，报告标记 `calibrationStatus=not-fitted-no-independent-data` 和 `probabilitiesCalibrated=false`。只按最高概率类别路由时温度不影响类别选择，但概率值不能视为校准后的真实可靠程度；将来若使用置信度门槛，需提供未参与全量训练的新校准题。不能直接复用历史 0.7 或 0.0908 门槛。

本轮产物写入独立目录，保留原始 checkpoint、五折模型与失败日志，不自动替换当前 230 的 fold-0 服务，也不访问 233。

### 最终模型训练完成（2026-10-10）

`final-all663-epochs20` 已训练并保存成功，核查实际训练包含全部 663 道题、每轮 1,404 行且三类各 468 行，配置仍为 20 轮冻结编码器。完整输入最长 972 tokens，无截断；损失从第一轮 1.1410 降至最后一轮 0.3155，训练耗时约 154.68 秒（不含加载、保存及回放），峰值 PyTorch allocated 1,554.18 MiB（约 1.52 GiB）。原始权重和配置哈希未变。

保存后重新加载，并用真实 `Agent.predict` 对全部训练题单题回放：难度标签准确率 90.95%、宏平均召回率 93.07%；简单召回 98.00%、中等召回 91.03%、困难召回 90.17%。这些都是 **训练题回放**，不能与此前五折 77.38% 的独立折内测试成绩直接比较，更不能视作最终模型的泛化准确率或数学解题正确率。

| 最终模型训练题回放规则 | 本地放行/663 | 覆盖率 | 有历史评估的放行题 | 未评估放行题 | 历史已判定推理错误率 | review 次数 |
|---|---:|---:|---:|---:|---:|---:|
| 仅预测简单 | 75 | 11.31% | 75 | 0 | 2/223＝0.90% | 2 |
| 预测简单或中等 | 240 | 36.20% | 237 | 3 | 25/701＝3.57% | 10 |

上述解题评估是训练题的既有本地推理结果，并非用最终路由系统重新解题。分别有 2 道和 20 道放行题至少一次本地答错。模型学习难度标签而非作答能力，仍可能将困难题预测为简单；全部题参与训练后，没有剩余独立校准或测试数据，不据此选择新门槛。

直接重新加载最终模型测试“求方程 x² − 5x + 6 = 0 的解。”，返回 `simple`，概率 simple=0.7282、medium=0.0462、difficult=0.2256，无截断。这是 SDK 直接调用测试，不是当前 8000 服务的返回；服务仍加载三分类 fold-0。温度保持 1.0，概率尚未独立校准，不能将 72.82% 当作可靠性或答对概率。

最终模型目录：`/data/metahuman_work/laya-math-training/difficulty-threeclass-v1/final-all663-epochs20/`，其中包含权重、编码器/分词器、任务原文、训练报告和全量回放。轻量报告保存到本地 `data/math-router/difficulty-threeclass-final-all663-results/`。本轮未部署最终模型，230 当前服务和 233 均未替换；后续使用概率门槛前需补充独立校准数据。

### 随后按用户要求切换 230 服务

已将 230 的 8000 服务从三分类 fold-0 切换为最终全量模型，模型别名仍为 `multilingual`。实际 HTTP 请求确认 `routing.repo` 指向 `final-all663-epochs20`；方程题返回简单 72.82%、中等 4.62%、困难 22.56%，与 SDK 直接加载一致，无截断、CUDA 正常、无 CPU fallback。服务保持后台运行，日志位于最终模型目录的 `serve-final.log`，未配置开机自启；原始与五折 checkpoint 均保留，233 未改动。此切换是用户授权的测试服务变更，不构成独立泛化评估或概率校准。
