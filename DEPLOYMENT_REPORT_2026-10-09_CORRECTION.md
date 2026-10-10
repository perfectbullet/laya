# Laya 部署报告（230 / 233，最终版）

当前 230 测试环境版本固定为 `final-all663-epochs20`，任务为数学难度三分类，验收关注人工难度标签的一致性，不关注解题模型是否答对。接口用法和参数迁移见 `docs/math-difficulty-test-api.zh-CN.md`，分类指标见 `docs/math-router-finetune.zh-CN.md` 开头的当前评估目标。此前 local/online 和解题错误率内容保留为历史实验记录。233 生产服务未变更。

报告日期：2026-10-09（Asia/Shanghai）；2026-10-10 补充 230 驱动修复后的实测与训练条件。  
核查方式：通过 `zenking` 账户进行只读 SSH 检查；不记录 API Key、HF Token 或其他密钥值。

本文件是可独立使用的最终版报告。它包含 233 的已运行服务详情，并以已核实的 230 信息替换此前误写的 231 信息。

## 修正后的结论

- **233（`192.168.100.233`）**：已验证的生产/内网推理节点；服务发布为 `0.0.0.0:8000`，离线缓存已包含 English、multilingual、typed-decisions，PyTorch 为 `2.14.0+cu126`，其 wheel 包含 V100 所需的 `sm_70`。下文 233 数字保留此前观测，本轮未重新测量。
- **230（`192.168.100.230`）**：2026-10-10 已实测驱动恢复、CUDA 正反向计算正常，Laya 三个 checkpoint 均在 CUDA 上运行。RTX 4080 16 GB 可作为数学路由训练候选节点；当前空闲约 10.4 GiB，正式训练峰值尚未测量。

## 233：当前生产/内网推理节点

| 项目 | 当前状态 |
|---|---|
| 主机名 / 地址 | `chanjing-ai` / `192.168.100.233/24`（`enp3s0`） |
| 架构 | `x86_64` |
| GPU | Tesla PG503-216（V100，32 GB 显存，sm_70） |
| NVIDIA 驱动 | `580.178.04` |
| Docker | Engine `29.1.3`、Compose `v2.30.3`、NVIDIA runtime 已配置 |
| 项目目录 | `/data/metahuman_work/laya` |
| 原始本地模型目录 | `/data/metahuman_work/laya-models/laya` |
| 服务容器 | `laya-laya-serve-1` |
| 服务状态 | `Up`，Docker 健康检查通过 |
| 内网端口 | `0.0.0.0:8000 -> 8000/tcp` |
| 健康检查 | `GET http://127.0.0.1:8000/health` 返回 `{"status":"ok"}` |

### 运行配置

部署使用以下 Compose 组合：

```bash
docker compose \
  -f compose.yaml \
  -f compose.http.yaml \
  -f compose.modelscope.yaml \
  -f compose.cuda.yaml \
  up -d --build --force-recreate --wait laya-serve
```

已核实的非敏感运行变量：

```text
LAYA_DEVICE=cuda
LAYA_PRELOAD=1
LAYA_MODELS=english,multilingual,typed-decisions
LAYA_AUTO_TASK=0
HF_HUB_OFFLINE=1
LAYA_PORT=8000
```

容器使用 `torch 2.14.0+cu126`（CUDA 12.6），wheel 包含 `sm_70`。因此它支持 V100；此前 `cu130` wheel 不包含 `sm_70`，会导致 `no kernel image is available for execution on the device`，不得在 233 使用。

### 模型、调用与鉴权

ModelScope 已将全模型族预取为 Hugging Face 离线缓存。缓存含有以下 checkpoint，且每个均存在 `rl_agent_config.json`：

```text
convaiinnovations/laya/                         # English root checkpoint
convaiinnovations/laya/multilingual/            # multilingual checkpoint
convaiinnovations/laya/typed-decisions/          # typed-decisions checkpoint
```

服务运行时不依赖 Hugging Face 网络访问。Docker 卷包括 `laya-all-model-cache`（当前全模型缓存）与 `laya_model-cache`（早期/单模型缓存）；容器内缓存路径是 `/home/laya/.cache/huggingface`。

内网服务地址：

```text
http://192.168.100.233:8000
```

服务配置了 `LAYA_API_KEY`，报告不记录其值。客户端请求 `/v1/systemone` 或 `/v1/systemone/batch` 时必须发送：

```http
Authorization: Bearer <LAYA_API_KEY>
```

可通过 `model` 指定 `multilingual` 或 `typed-decisions`；由于全模型族已缓存，省略该字段时 Router 也可自动路由。

### 233 的容量与运行风险

| 资源 | 当前观测 | 建议 |
|---|---:|---|
| 根分区 | 914 GB 总计；831 GB 已用；45 GB 可用（95%） | **高风险。** 在构建、下载或微调前先清理或扩容。 |
| Docker 镜像 | 368 GB；约 206.9 GB 可回收 | 清理前盘点其他在线服务。 |
| Docker Build Cache | 97.89 GB；约 53.04 GB 可回收 | 优先评估的回收对象。 |
| Docker 卷 | 9.055 GB | 不得删除 `laya-all-model-cache`。 |
| GPU | 与 embedding、reranker、TTS、Milvus 等服务共用 | 训练前必须核实显存，并隔离或停机在线服务。 |

## 230 服务修复验证快照

| 项目 | 当前状态 |
|---|---|
| 主机名 / 地址 | `zenking` / `192.168.100.230` |
| 架构 | `x86_64` |
| Laya 项目目录 | `/data/metahuman_work/laya` |
| 本地模型目录 | `/data/metahuman_work/models/laya` |
| 模型大小 | 2.3 GB |
| 本地 checkpoint | English 根模型、`multilingual`、`typed-decisions`；均有 `rl_agent_config.json` |
| Laya 容器 | 未发现 |
| Laya HTTP 服务 | `laya-serve` PID 50204，监听 `0.0.0.0:8000`；本机 `/health` 成功 |
| GPU | NVIDIA GeForce RTX 4080，16,376 MiB，计算能力 8.9 |
| NVIDIA 驱动 | `595.99.02`；`nvidia-smi` 正常，原 NVML 版本不匹配问题已恢复 |
| Python / PyTorch | Python `3.12.15`，PyTorch `2.14.1+cu130`，运行时 CUDA `13.0` |
| Conda 环境 | `/data/qianyong/miniconda3/envs/laya` |
| 根分区 | 914 GB 总计，741 GB 已用，136 GB 可用（85%） |
| 数据盘 | 1.8 TB 总计，1.6 TB 已用，114 GB 可用（94%） |

### 230 验证范围与结果

本轮通过 SSH 只读核查服务、环境、模型配置和资源，并执行一次小型 CUDA 矩阵正反向计算与一次 multilingual HTTP 预测。没有启动训练、停止服务或修改服务器配置。

- `torch.cuda.is_available()` 为 `True`，小型 CUDA forward/backward 成功；此验证说明基础计算可用，不等于已完成 Laya 全参数微调兼容性和峰值显存测试。
- `/health` 返回 `status=ok`，`loaded=[english,multilingual,typed-decisions]`，实际 device 和三个 checkpoint 的 device 均为 `cuda`，CPU fallback 计数均为 0。
- 三个 checkpoint 的服务 revision 均为 `7b928d828b7b0e022f929d9bd2e44165aa270148`。
- `POST /v1/systemone` 指定 `model=multilingual` 成功返回二分类 probabilities；测试题未截断。测试使用简短探针提示词，仅验证服务功能，不衡量 v3 或微调路由质量。
- 已核实 `LAYA_DEVICE=cuda`、`LAYA_PRELOAD=1`。服务环境未设置 `LAYA_MODELS`、`HF_HUB_OFFLINE` 或 `LAYA_API_KEY`；本机无 Authorization 的预测请求成功。不能假设其鉴权和离线设置与 233 相同。
- 完整仓库的离线 `snapshot_download` 报告缺少 README、assets 等文件；所需 multilingual 配置可直接读取，服务实际推理正常。这不说明模型权重损坏，也不表示已配置强制离线运行。
- 当前服务 revision 的 multilingual 配置为 `max_len=1024`、`head_max_len=256`、`temperature=[1.0,1.0,1.0]`、`temperature_by_options={}`。本地原始模型目录具有 `encoder/`、`tokenizer/`、`model.safetensors` 和 `rl_agent_config.json`。
- `laya.train` 和训练 CLI 可导入，包含冻结编码器、soft-ce、学习率、micro-batch、梯度累积和评估文件等参数。

### 启动日志中的温度警告

用户提供的启动日志提示 `choice:11+=0.10058280825614929` 超出允许范围，运行时将其限制到 0.5。检查 English 原始 checkpoint 配置可找到该项。

该项针对 English 模型的 11 个及以上候选项 bucket；数学路由固定使用 multilingual 且只有两个候选项，因此不直接命中该条配置。服务 revision 的 multilingual 配置没有分桶温度条目。这个警告并非 CUDA 故障，也不能证明 multilingual 的数学路由概率已经校准；微调后仍须在独立校准数据上重新拟合温度和选择路由阈值。

### 230 训练资源评估

本轮 `nvidia-smi` 快照：总显存 16,376 MiB，已用 5,723 MiB，余量约 10,653 MiB（10.4 GiB）。其中：

| 进程 | 用途 | 显存 |
|---|---|---:|
| PID 50204 | `laya-serve`，预加载三个 checkpoint | 4,886 MiB |
| PID 2402 | `python spk_id_utils.py` | 822 MiB |

建议优先在 230 开展训练。冻结编码器基线可先试 `micro_batch=2`、`grad_accum=8`；全参数基线启用 FP16 和梯度检查点，仍从 micro-batch 1–2 开始。上述是试跑建议，不是已测峰值显存。题面 token 长度检查通过后再决定序列预算，不应为省显存而无记录地截断题目条件。

当前余量足以尝试小批量训练，但不能保证全参数微调与三个服务模型并存时不会 OOM。如需更多余量，可在另行安排服务窗口后释放 Laya 推理进程，或减少其预加载模型；本轮没有执行这些操作，也没有操作语音服务。训练输出写入独立目录，当前 `/data` 约 114 GB 可用，应监控每轮 checkpoint 的磁盘占用。

## 更新后的微调安排

1. 230 驱动和基础 CUDA 验证已通过，优先作为训练节点；233 保留生产推理用途。
2. 将本地已准备的分层五折数据、固定任务定义和训练包装代码同步到 230 前，明确数据版本；本轮尚未同步或训练。
3. 先用 multilingual tokenizer 做数据 dry-run，记录题面截断情况，再做一个短训练试跑测峰值显存和实际训练兼容性。
4. 230 的 `cu130` 环境已在 RTX 4080 上完成基础计算验证，不能据此将该环境复制到 233 的 V100；233 仍使用支持 `sm_70` 的环境。
5. 微调输出必须写入独立目录，例如 `/data/metahuman_work/laya-finetunes/<run-id>`，不得覆盖原始模型或生产服务缓存。

## 2026-10-10 补充：训练准备与短试跑

以下为后续实测，以上 PID 50204 和服务健康情况是此前修复验证的快照，不能当作当前状态。短试跑前本机 `127.0.0.1:8000/health` 连接被拒绝，未发现该端口的运行服务；本轮没有启停 Laya 或语音进程。RTX 4080 已用约 831 MiB、空闲约 15,115 MiB，数据盘仍约 114 GB 可用。

已将训练包装脚本及派生数据同步到 `/data/metahuman_work/laya-math-training/20261010/`。每折训练 168 行（132 local、36 online，online 仅在训练集重复三次），校准/测试各 48 行（44 local、4 online），保持固定切分和自然分布。未传输 `.env` 或 MongoDB 连接凭据。

使用 `/data/metahuman_work/models/laya/multilingual` tokenizer 检查全部 240 道题：最长题面 255 tokens、完整序列最长 332 tokens，1024 序列预算内没有截断。沿用 230 原有 Conda 环境，无新依赖安装。

已完成 fold-0 冻结编码器、1 epoch、micro-batch 2、grad-accum 8 的短试跑。PyTorch 峰值分配显存 1,489.63 MiB、缓存保留峰值 1,568 MiB；不含其它进程和 CUDA 驱动开销，不是全参数训练峰值。训练及前后测试/校准计算约 2.06 秒，不含初始化和保存。独立产物写入 `fold-0-frozen-smoke/`，没有覆盖原始模型、服务缓存或生产配置。

短试跑测试分类准确率训练前后均为 50%，校准温度达到 5.0 上限，不具备生产替换条件。保存后重新加载检查：默认 P(local)>=0.5 放行 24/48，误放行 2 道历史风险题；只在校准集选择的开发门槛约 0.544563，在测试集放行 8/48、误放行 0。样本量不足以证明未知题 98% 正确率，未自动部署。详细命令、报告位置及局限见 `docs/math-router-finetune.zh-CN.md`。

## 2026-10-10 补充：完整五折训练与模型替换测试

微调基座为 **Laya multilingual**，原始目录 `/data/metahuman_work/models/laya/multilingual/`，不是数学解题模型。原始权重与 `convaiinnovations/laya` 的缓存 revision `7b928d828b7b0e022f929d9bd2e44165aa270148` 的 multilingual 权重哈希一致：

- 权重 SHA-256：`9d628fd971b700382ac6f65920a86f149777b2e748e0c955fb3b19695aa8f204`。
- 配置 SHA-256：`25061739243b617ad88d1219ba6f8a9c86c5881ca28df024fa2d9b3b2fcc30c6`。

两种采样方案各五折已训练完成，每折 4 epochs、micro-batch 2、grad-accum 8，编码器参数冻结，只更新其余 14,969,347 个决策网络参数。每折均重新加载原始权重，未覆盖基座。训练前后原始权重/配置哈希一致；PyTorch 峰值 allocated 最大约 1.46 GiB。全部产物在 `/data/metahuman_work/laya-math-training/20261010/frozen-fivefold-v1/`，按 `online1x/fold-0..4`、`online3x/fold-0..4` 分开。

初次 HTTP 测试发现 FP32 训练回放与实际 BF16 服务概率不同，已保留初次失败报告，补做 `Agent.predict` 服务路径的完整五折校准/测试回放。以下最终数字来自 `summary-runtime.json`，不再使用 FP32 报告做服务路由结论：

| 方案（同一 math_route 任务定义） | 本地放行/240 | 历史风险题误放行 | 放行集合历史安全标签比例 |
|---|---:|---:|---:|
| 原始 multilingual | 8 | 0 | 100%，仅 8 题 |
| 冻结编码器，不重复采样 | 34 | 2 | 94.12% |
| 冻结编码器，online 三倍采样 | 35 | 2 | 94.29% |

各折门槛仅由校准集选择，不使用测试标签调门槛。表内比例不等于最终 solver 正确率，也不是既有难度 v3 生产策略的对照。这次冻结基线尚无充分生产替换依据。

已在 230 临时 localhost:8000 测试服务中依次把 `multilingual` 映射到两个方案预先指定的 fold-0 checkpoint，各执行 48 道真实 `/v1/systemone` HTTP 请求。health 显示 CUDA，CPU fallback 0；输入无截断，概率与运行时回放一致。两个方案按自己的校准门槛分别放行 7 道、8 道，没有历史风险误放行。临时测试进程已关闭，没有覆盖原始模型或留下常驻测试服务。233 生产服务未访问、未修改。完整复现命令和结论见 `docs/math-router-finetune.zh-CN.md`。

## 后续实验：online-risk-v1

230 已完成风险检测提示词的原始模型五折回放，以及普通采样/online 三倍采样两个方案的五折冻结编码器微调（各 4 epochs）。标签和题目切分不变；门槛改为校准集风险题 P(online) 的最小值，确保校准风险题全部走 online，并尽量减少安全题误转。该规则不保证未知题零漏判。

实际 BF16 运行时五折测试均只召回 15/20 道风险题（75%），漏判 5 道。原始模型、普通采样微调、三倍采样微调分别误转 132/220、130/220、135/220 道历史安全题。没有充分证据支持部署；233 服务保持不变。

新实验产物独立保存在 `/data/metahuman_work/laya-math-training/online-risk-v1/`。训练峰值 PyTorch allocated 最大约 1.46 GiB，原始权重和配置哈希不变。两种微调方案各完成 48 道临时 HTTP 检查，概率/阈值决策一致、无截断、无 CPU fallback，测试进程已关闭。三倍采样是训练曝光加权，不是严格 weighted-CE 损失；未改变 Laya 公共训练 API，未进行全参数训练。详细表格和命令见中文训练文档的 online-risk-v1 章节。

## 后续实验：全部 20 道 online 参与每折训练

按用户要求，在 230 的 `/data/metahuman_work/laya-math-training/all-online-v1/` 重做两个方案各五折训练，每模型 4 epochs、冻结编码器。每折训练包含原来的 132 道 local 加全部 20 道独立 online；三倍采样重复 online 为 60 行。local 校准/测试各保持原来的 44 道。没有独立 online 测试样本。

online 门槛参考题是同样 20 道已训练题，与 44 道 local 校准题组成混合参考集，明确标记 `riskCalibrationIsTrainingReplay=true`。这个集合的温度拟合和阈值选择不是独立风险校准；训练风险题按门槛回放 20/20 是选阈值的构造结果，不能证明未知风险召回。

五折独立 local 测试共 220 道，普通采样误转在线 201 道（91.36%），三倍采样 189 道（85.91%）。默认 P(online)>=0.5 时各模型对训练风险题均识别 0/20；未形成可用生产替换依据。测试的 onlineRecall 为 null，未伪称 100%。产物在 `all-online-v1/frozen/`，原始权重/配置哈希不变。

两个方案预先固定的 fold-0 checkpoint 各执行 64 次临时 HTTP 请求，分别报告 44 道独立 local 测试和 20 道 online 训练题回放；检查通过后关闭自己创建的进程。233 生产服务仍未修改。复现参数、评估局限与结果见中文训练文档的 all-online-v1 章节。

### 2026-10-10：增加至 20 轮的训练对照

230 在独立目录 `/data/metahuman_work/laya-math-training/all-online-v1/frozen-epochs20/` 完成普通采样和 online 三倍采样各五折、每模型 20 epochs 的冻结编码器训练，仍从原始 multilingual 重新训练。与四轮对应方案的训练配置仅轮数不同，数据 manifest 和各折测试题集合一致；原始模型未覆盖。

独立 local 测试共 220 道：普通采样误转在线由四轮的 201 道降至 153 道（69.55%），三倍采样由 189 道降至 86 道（39.09%），三倍采样留在本地的题由 31 道增至 134 道。默认 0.5 门槛下，三倍采样各折训练风险识别为 8–10/20；使用训练风险最小概率选门槛后仍为 20/20，此数值不是独立未知风险召回率。没有新增独立 online 校准或测试样本，温度仍采用混合参考集的 FP32 拟合，本轮不能证明生产解题正确率达到 98%。

峰值 PyTorch allocated 最大约 1.46 GiB；两个预先固定的 fold-0 各通过 64 次 HTTP 请求，未截断、无 CPU fallback，临时服务和训练进程均已退出。结束后 GPU 已用 1 MiB、空闲 15,945 MiB，数据盘空闲约 88 GiB。233 未访问或修改，本轮不部署模型。详细命令、四轮/二十轮对比与局限见 `docs/math-router-finetune.zh-CN.md` 的二十轮章节。

### 2026-10-10：第二版难度三分类，过滤超长题

从 MongoDB 导出 665 道人工难度标签题，将压轴归入困难。按用户要求，排除超过本轮题面预算的 `ZP-MATH-5_4_27` 和 `ZP-MATH-5_7_34`，仅影响实验快照，不删除题库记录。剩余 663 道（简单 50、中等 145、困难 468），完整输入最长 972 tokens，低于总上限 1024。

在 `/data/metahuman_work/laya-math-training/difficulty-threeclass-v1/frozen-epochs20-filtered/` 完成分组五折、每模型 20 轮冻结编码器训练。仅训练集均衡三类重复采样，校准/测试自然分布且完全独立；温度使用保存后模型的 BF16 实际运行时 logits 拟合。测试准确率 77.38%、宏平均召回率 62.13%；同三分类提示词的原始模型准确率 13.57%，不是旧二分类生产方案的直接对照。

“简单＋中等”走 local 放行 234/663（35.29%），其中 215 道有历史本地评估，已判定推理错误率 26/633（4.11%），另 19 道无评估、12 次 review。仅简单走 local 放行 72/663，历史已判定错误率 10/198（5.05%）。这些是历史子集指标，不是端到端或未知题正确率；困难题仍会被误判简单。

训练峰值 PyTorch allocated 最大约 1.52 GiB，训练进程已退出。原始 multilingual 哈希不变；230 原有 8000 服务健康、CUDA 正常、无 CPU fallback。本轮三分类模型没有部署，233 未访问或修改。完整排除记录、切分、混淆矩阵和局限见中文训练文档的第二版章节。

### 2026-10-10：663 道全量最终模型

按用户要求固定已验证的参数，在 `/data/metahuman_work/laya-math-training/difficulty-threeclass-v1/final-all663-epochs20/` 完成最终训练：全部 663 道题，三类均衡采样后每轮 1,404 行，20 轮冻结编码器，从原始 multilingual 重新训练，不续训 fold-0。原始模型及五折权重保留；训练阶段峰值 PyTorch allocated 约 1.52 GiB，训练约 154.68 秒。

全量训练题回放难度准确率 90.95%，不是独立测试或解题正确率。没有独立校准集，因此温度明确设为 1.0、不沿用五折温度，报告标记 `probabilitiesCalibrated=false`、`independentEvaluationAvailable=false`。最高概率路由无需依赖旧的概率门槛，但若要用置信度放行，须先补充新校准题。

保存后重新加载最终模型，直接调用 SDK 测试二次方程题，返回简单（simple=0.7282、medium=0.0462、difficult=0.2256），无截断。本轮没有替换 230 当前三分类 fold-0 服务，也没有访问或修改 233。全量回放、标签与训练配置见最终目录的报告；本地轻量报告在 `data/math-router/difficulty-threeclass-final-all663-results/`。

### 2026-10-10：最终模型服务切换与 HTTP 测试

随后按用户明确要求，核实并停止 230 原 fold-0 服务进程 157059，保留其 checkpoint，将 `multilingual` 映射切换到 `/data/metahuman_work/laya-math-training/difficulty-threeclass-v1/final-all663-epochs20/`。服务以独立后台进程监听 `0.0.0.0:8000`，对外地址 `http://192.168.100.230:8000`；日志为最终模型目录的 `serve-final.log`。这是运行中的后台进程，不是已配置开机自启的服务。

实际 POST `/v1/systemone` 使用训练时相同三分类任务说明，题面为“求方程 x² − 5x + 6 = 0 的解。”，返回 simple=0.7282、medium=0.0462、difficult=0.2256，选择 simple；返回的 `routing.repo` 确认为最终模型目录，与之前 SDK 测试一致。输入 171 tokens、题面 18 tokens，无截断；health 显示 CUDA、CPU fallback 为 0。按最高概率分类，两种难度路由规则均将此题送 local；接口只判断难度，未调用解题模型。概率尚未独立校准，不是实际答对率。233 未访问或修改，旧模型文件未删除。
