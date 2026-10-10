# Laya 部署报告（230 / 233，最终版）

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

## 230 当前实测状态

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
