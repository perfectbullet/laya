<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/NandhaKishorM/laya/main/assets/logo-lockup-dark.png" />
    <img src="https://raw.githubusercontent.com/NandhaKishorM/laya/main/assets/logo-lockup.png" alt="Laya" width="330" />
  </picture>
</p>

**多语言、非自回归的 System 1 决策引擎。** 它能在一次前向传播中，对 100 多种语言做出类型化决策（33 ms）；模型通过针对严格适当评分规则的强化学习（RLCD）训练，并由路由器为每个请求选择合适的 checkpoint。

<div align="center">

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/drive/15d4Yv__KHeHjshVb-6PRTfqVllxih2S3?usp=sharing)
[![PyPI version](https://img.shields.io/pypi/v/laya.svg)](https://pypi.org/project/laya/)
[![Docs](https://img.shields.io/badge/docs-online-2ea44f)](https://nandhakishorm.github.io/laya/)
[![Hugging Face Model](https://img.shields.io/badge/%F0%9F%A4%97%20Model-convaiinnovations%2Flaya-blue)](https://huggingface.co/convaiinnovations/laya)
[![Multilingual](https://img.shields.io/badge/%F0%9F%A4%97%20Model-laya--multilingual-blue)](https://huggingface.co/convaiinnovations/laya-multilingual)
[![Hugging Face Space](https://img.shields.io/badge/%F0%9F%A4%97%20Space-laya--demo-orange)](https://huggingface.co/spaces/convaiinnovations/laya-demo)
[![Dev.to Article](https://img.shields.io/badge/dev.to-Read%20Article-0A0A0A?logo=devdotto&logoColor=white)](https://dev.to/nandakishor_m_6cc0adfde9f/i-built-non-autoregressive-decision-models-a-year-ago-then-a-frontier-lab-called-it-a-18me)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-nandakishorm-FFDD00?logo=buy-me-a-coffee&logoColor=black)](https://www.buymeacoffee.com/nandakishorm)
[![License](https://img.shields.io/badge/License-Apache%202.0-green.svg)](https://opensource.org/licenses/Apache-2.0)

</div>

> 本文是英文 [README.md](README.md) 的中文版本。命令、代码、API 名称、环境变量及链接保持原样；英文原文仍是项目的权威版本。

## 安装

```bash
python -m pip install laya
```

如果使用 [uv](https://docs.astral.sh/uv)，可在 uv 项目中运行 `uv add laya`，或在虚拟环境中运行 `uv pip install laya`。

需要 Python 3.10 或更高版本。可选扩展包括：`laya[serve]`（HTTP 服务）、`laya[mcp]`（MCP 服务）、`laya[langchain]`（LangChain 与 LangGraph）、`laya[llamaindex]`（LlamaIndex 选择器）、`laya[crewai]`（CrewAI 路由）、`laya[onnx]`（ONNX Runtime）和 `laya[fast]`（TileLang GPU 快速路径）。各平台的逐步安装说明、仅 CPU 或 GPU PyTorch 构建方式，以及故障排查见[安装详情](#安装详情)。

如需 TypeScript / Node.js / 浏览器支持，请查看 [`laya-ts/`](https://github.com/NandhaKishorM/laya/tree/main/laya-ts/)。npm 发行版（`npm install laya-ts`）由本仓库的 `laya-ts-v*` release tag 发布。

**长文档。** `laya-multilingual` 在 `max_len=8192` 时可读取最多 8,192 个 token。按文档长度测得的准确率和耗时可通过 [`research/scripts/bench_long_context.py`](https://github.com/NandhaKishorM/laya/blob/main/research/scripts/bench_long_context.py) 复现：

<p align="center">
  <img src="https://raw.githubusercontent.com/NandhaKishorM/laya/main/assets/long_context_8192.png" alt="laya-multilingual with max_len=8192: 16 to 18 of 20 requests correct with up to about 4,000 tokens of text before them, more variable beyond" width="100%" />
</p>

## 快速开始

> **长文档：`laya-multilingual` 最多读取 8,192 个 token。** 它默认的 1,024-token 限制会截断长文档，因此请为长文档传入 `max_len=8192`：
>
> ```python
> result = router.predict(long_document, questions, model="multilingual", max_len=8192)
> ```
>
> 上表中，正文之前最多约有 4,000 个 token 时，20 个请求中有 16 至 18 个回答正确；超过该长度后结果波动较大（20 个中为 8 至 17 个），请在自己的数据上验证长文档准确率。短输入在 `max_len=8192` 下的回答完全一致，速度取决于真实输入长度而非该上限：短输入不会变慢，4,000-token 输入在 Apple GPU 上约需 1.7 秒。请以 `model="multilingual"` 指定 checkpoint；否则主要为英文的长文本可能会被路由到 English checkpoint。

```python
from laya import Router

router = Router()  # 首次使用时下载 checkpoint；Router(preload=True) 会预先加载全部三个模型

state = "Hi, we were billed twice for March. Please refund the duplicate today or we will cancel our plan."
questions = {
    "department": {"type": "choice", "instructions": "Which department should handle this?",
                   "criteria": {"billing": "invoices, payments, refunds",
                                "technical": "bugs, outages, system errors",
                                "other": "everything else"}},
    "urgency": {"type": "score", "instructions": "How urgent is this?",
                "criteria": ["not urgent", "soon", "blocking"]},
    "churn_risk": {"type": "noul", "instructions": "Does the user threaten to cancel or leave?"},
}

result = router.predict(state, questions)
print(result["answers"]["department"]["choice"])  # billing
print(result["answers"]["churn_risk"]["noul"])    # probability the answer is yes
print(result["routing"]["model"])                 # english
```

同一调用适用于 100 多种语言。`Router` 会检测文字系统和语言，并将非英语文本发送至 `laya-multilingual`：

```python
for text in ["मुझसे मार्च में दो बार शुल्क लिया गया, कृपया डुप्लिकेट राशि वापस करें।",
             "La aplicación se cierra cada vez que abro la configuración."]:
    r = router.predict(text, {"department": questions["department"]})
    print(r["routing"]["model"], r["answers"]["department"]["choice"])
# multilingual billing
# multilingual technical
```

命令行中，`laya "My payment failed twice" --preset triage` 会回答一组预置问题。更多内容见[完整快速开始](#快速开始路由模式推荐)和[文档](https://nandhakishorm.github.io/laya/)。

## 通过微调提高准确率

随附 checkpoint 可以零样本使用；但在自己的领域决策数据上微调，准确率会显著提升。在 typed-decisions 基准（跨四个工作流的 2,000 个决策）上，微调后的 `laya-typed-decisions` checkpoint 准确率为 **0.766**，而基础 English checkpoint 在相同决策上的准确率为 **0.362**。

**[微调 Notebook](https://github.com/NandhaKishorM/laya/blob/main/notebooks/laya_finetune_typed_decisions_2xT4_kaggle.ipynb)**（Kaggle 2xT4）和 **[Apple Silicon 脚本](https://github.com/NandhaKishorM/laya/blob/main/notebooks/laya_finetune_typed_decisions_mps.py)**（MPS / CPU）可运行完整流程：构建数据集、使用 RLCD 训练、校准温度、评估与导出。详见[微调](#微调)。

## 文档

**[nandhakishorm.github.io/laya](https://nandhakishorm.github.io/laya/)**：包含[预测钩子](https://nandhakishorm.github.io/laya/hooks/)、[由 Schema 驱动的决策](https://nandhakishorm.github.io/laya/structured/)、[Docker](https://nandhakishorm.github.io/laya/docker/)和[LangChain 与 LangGraph](https://nandhakishorm.github.io/laya/langchain/)指南，以及完整的 [API 参考](https://nandhakishorm.github.io/laya/reference/)。

## 0.4.0 的更新

* **路由默认值现为 `multilingual`。** 语言检测器无法确定语言的文本过去会回退到 English checkpoint。在 51 种语言的测试中，multilingual checkpoint 在其中 50 种语言上领先；唯一例外是英语本身（0.820 对 0.710）。排除英语后，宏平均准确率领先 0.180。已识别为英语的文本仍会路由至 English checkpoint，因此只有未能确定的文本改变行为。设定 `Router(default="english")` 或 `LAYA_DEFAULT_MODEL=english` 可恢复旧行为；分界点约为 62% 的英文流量。

早期版本见 [GitHub releases](https://github.com/NandhaKishorM/laya/releases)。

---

<p align="center">
  <img src="https://raw.githubusercontent.com/NandhaKishorM/laya/main/assets/laya_vs_jev_full.png" alt="Laya versus TypeSafe Jev: accuracy on shared public datasets, every application workflow, all 51 languages, speed, calibration, and the cost of not preloading" width="100%" />
</p>

Laya 可针对任意 state（文本、邮件、工单或 JSON 文档）中的类型化问题（`choice`、`score`、`noul`），在**一次前向传播**中给出答案：T4 上单题 33 ms，批处理为每题 7.2 ms。它不生成文本，因此没有要解析的内容，也不会出现幻觉。

共有三个 checkpoint，并由 `Router` 为每个请求选择其一：

| | 编码器 | 参数量 | 上下文 | 适用场景 |
|---|---|---:|---:|---|
| [`laya`](https://huggingface.co/convaiinnovations/laya) | ModernBERT-large | 421M | 512 | English |
| [`laya-multilingual`](https://huggingface.co/convaiinnovations/laya-multilingual) | mmBERT-base | 322M | 1024（最高 8,192） | 100 多种语言，速度快 2 倍 |
| [`laya-typed-decisions`](https://huggingface.co/convaiinnovations/laya-typed-decisions) | ModernBERT-large | 421M | 1024 | typed-decisions 工作流 |

## 下一步阅读

| 文档 | 内容 |
|---|---|
| 下方快速开始 | 最短路径：完成一次可用调用 |
| [`examples/README.md`](https://github.com/NandhaKishorM/laya/blob/main/examples/README.md) | 41 个可运行示例，构成八阶段学习路径：首次调用 → Schema 设计 → 生产服务 |
| [`LOCAL_SETUP.md`](https://github.com/NandhaKishorM/laya/blob/main/LOCAL_SETUP.md) | 在 macOS/Intel 上运行此 checkout：固定依赖栈、checkpoint 清单、两个可移植性修复，以及全部验证运行和结果 |
| [`BENCHMARKS.md`](https://github.com/NandhaKishorM/laya/blob/main/BENCHMARKS.md) | 汇总的全部 benchmark、全部 51 种语言，以及明确说明的限制 |
| [`research/README.md`](https://github.com/NandhaKishorM/laya/blob/main/research/README.md) | 生成这些指标的测试 harness，以及如何重新运行 |

## 安装详情

需要 Python 3.10 或更高版本。依赖决定了这一最低版本：`huggingface_hub` 1.x、`transformers` 5.x 和 `torch` 2.14 都要求 Python 3.10。

**可选的 PyTorch 构建选择：** 如需仅 CPU 或针对特定 GPU 的 PyTorch 构建，请在创建虚拟环境后、安装 Laya 前，遵循 [PyTorch 安装指南](https://pytorch.org/get-started/locally/)。将所选命令中的 `pip` 或 `pip3` 替换为环境 Python 可执行文件加 `-m pip`。

若已经使用虚拟环境，请安装 PyPI 发行版：

```bash
python -m pip install laya
```

对于新环境，请按下面的平台选择命令。在项目目录中执行；显式 Python 路径可确保安装和验证处于同一环境。

**macOS / Linux**（Python 3.10 或更新版本）：

在 Debian/Ubuntu 上，系统 Python 可能要求先执行 `sudo apt install python3-venv` 才能创建虚拟环境。若 `venv` 报告 `ensurepip` 不可用，请安装该包后重试。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install laya
.venv/bin/python -I -c "import laya; print(laya.__version__)"
```

**Windows PowerShell**（以下示例使用已安装的 Python 3.11）：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install laya
.\.venv\Scripts\python.exe -I -c "import laya; print(laya.__version__)"
```

两种检查都会输出已安装的 Laya 版本，而不会加载 checkpoint。`-I` 会将当前目录排除在导入搜索路径之外，避免本地源码副本掩盖缺失的安装。运行应用程序时请持续使用同一虚拟环境的 Python。

**Intel GPU（XPU）**

请先安装受支持的 Intel GPU 驱动。若需启用 XPU 的 PyTorch 构建，请在安装 Laya 前安装其 wheel；默认 PyPI wheel 可能仅支持 CPU。PyTorch 已验证的硬件和操作系统列表见 [Intel GPU 指南](https://docs.pytorch.org/docs/2.14/notes/get_start_xpu.html)。

```powershell
.\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/xpu
.\.venv\Scripts\python.exe -m pip install laya
.\.venv\Scripts\python.exe -c "import torch; print(torch.xpu.is_available())"
```
