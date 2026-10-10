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
