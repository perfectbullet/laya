# 数学难度三分类：测试环境使用说明

## 当前版本

测试环境使用 `final-all663-epochs20`，而不是五折实验的 fold-0。访问地址为 `http://192.168.100.230:8000`，分类接口为 `POST /v1/systemone`，健康检查为 `GET /health`。

230 的 checkpoint 目录：

```text
/data/metahuman_work/laya-math-training/difficulty-threeclass-v1/final-all663-epochs20/
```

模型从原始 multilingual 微调，全部 663 道过滤后题目参与训练，20 轮、冻结编码器、三类均衡采样；“压轴”合并为“困难”。当前服务后台运行，日志位于上述目录的 `serve-final.log`，未配置开机自启。233 生产服务未变更。若重启服务器，需重新启动测试服务，并检查返回的 `routing.repo`。

当前目标是 **判断题目难度是否准确**，不是预测解题模型是否答对。输入只有题面，不需要提供难度、答案或解题模型名称。分类器不解题，也不直接返回 local/online；若业务需要路由，由调用方根据难度另行制定规则。

## 与旧版参数的变化

| 项目 | 历史版本 | 当前版本 |
|---|---|---|
| 服务地址 | 233 生产或 230 历史实验地址 | 本测试环境为 `192.168.100.230:8000` |
| 请求 `model` | `multilingual` | 不变，仍为 `multilingual`；其映射的 checkpoint 已改变 |
| 题目 `state` | 原始题面 | 不变，只输入题面 |
| 任务 ID | 路由实验为 `math_route`；早期难度实验为 `math_difficulty` | `math_difficulty` |
| `type` | `choice` | 不变 |
| 类别 | 路由实验 `local/online`；早期难度二分类 `simple/difficult` | `simple/medium/difficult` |
| 任务说明和类别描述 | 历史二分类提示词 | 必须使用当前训练时的三分类提示词 |
| 读取选择结果 | 旧任务的 `choice` 或基于概率门槛计算路由 | `answers.math_difficulty.choice` |
| 读取类别概率 | 旧任务的 `probabilities` | `answers.math_difficulty.probabilities`，含三个键 |
| 选择规则 | 曾使用 `P(simple)>=0.7` 或 `P(online)>=0.0908` | 最高概率类别；不沿用旧阈值 |

即使任务 ID 相同，二分类提示词和三分类提示词也不能混用。接口是通用决策接口，不会自动补充 checkpoint 目录中的 `questions.json`；客户端必须发送当前任务定义。输出键使用英文，展示时可映射为 simple＝简单、medium＝中等、difficult＝困难（含压轴）。

## 测试命令

只修改 `state` 中的题目文本，其他任务字段保持与训练一致：

```bash
curl -sS --fail-with-body --connect-timeout 5 --max-time 30 \
  http://192.168.100.230:8000/v1/systemone \
  -H 'Content-Type: application/json' \
  --data-raw '{
    "model": "multilingual",
    "state": "求方程 x² − 5x + 6 = 0 的解。",
    "questions": {
      "math_difficulty": {
        "type": "choice",
        "instructions": "仅根据数学题题面判断解题难度，选择简单、中等或困难。不要假设有外部难度标注，不要解题或输出答案。综合考虑知识点、推理步骤、条件分析和方法选择；不要仅因题面长或公式多就判为困难。压轴题归为困难。",
        "criteria": {
          "simple": "简单：基础概念、直接代入或常规计算，方法明确，推理步骤少。",
          "medium": "中等：需要若干推理或计算步骤、常规方法组合或一定的条件分析，但不需要复杂综合。",
          "difficult": "困难：需要复杂综合、关键方法构造、深入分类讨论或较长证明推导；包含压轴题。"
        }
      }
    }
  }' | python -m json.tool
```

`-sS` 隐藏进度条但显示错误；`--fail-with-body` 在 HTTP 错误时返回失败状态并保留响应体，旧版 curl 不支持此选项时可使用 `--fail`。连接和请求超时分别为 5 秒、30 秒。自动化脚本若保留上述管道，应启用 `set -o pipefail`，避免 JSON 格式化命令掩盖 curl 的退出状态。题目包含引号、反斜杠或换行时应使用 JSON 编码器生成请求，不能直接把未转义文本拼进 JSON 或 shell 命令。

也可在本仓库通过 Python 标准库调用，复用已保存的任务定义以避免手写参数不一致：

```python
import json
from pathlib import Path
from urllib.request import Request, urlopen

questions = json.loads(Path(
    "data/math-router/difficulty-threeclass-final-all663-results/questions.json"
).read_text(encoding="utf-8"))
payload = {
    "model": "multilingual",
    "state": "求方程 x² − 5x + 6 = 0 的解。",
    "questions": questions,
}
request = Request(
    "http://192.168.100.230:8000/v1/systemone",
    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
with urlopen(request, timeout=30) as response:
    result = json.load(response)
if result["usage"]["truncated"]:
    raise RuntimeError("题面被截断，不能作为完整题目的难度分类结果")
answer = result["answers"]["math_difficulty"]
print(answer["choice"], answer["probabilities"])
```

示例中的数据目录是本地实验产物，未提交 Git；从其他项目调用时，应复制当前任务定义，或读取 230 最终模型目录中的 `questions.json`。不要依赖对话里曾给出的旧二分类提示词。

## 输出字段

方程题已验证的实际 HTTP 响应节选：

```json
{
  "model": "laya-rl-agent",
  "answers": {
    "math_difficulty": {
      "type": "choice",
      "choice": "simple",
      "probabilities": {"simple": 0.7282, "medium": 0.0462, "difficult": 0.2256},
      "confidence": 0.3547,
      "answer_confidence": 0.7282
    }
  },
  "usage": {"input_tokens": 171, "state_tokens": 18, "state_tokens_dropped": 0, "truncated": false},
  "routing": {
    "model": "multilingual",
    "repo": "/data/metahuman_work/laya-math-training/difficulty-threeclass-v1/final-all663-epochs20",
    "reason": "explicit model='multilingual'"
  }
}
```

| 字段 | 使用方式 |
|---|---|
| `answers.math_difficulty.choice` | 主结果，最高概率类别；用于展示难度 |
| `probabilities.simple/medium/difficult` | 三类别概率分数；有舍入，和可能略偏离 1 |
| `answer_confidence` | 本例等于所选类别的最大概率 0.7282；不是额外独立评估结果 |
| `confidence` | 本 choice 任务为归一化熵转换的分布集中程度，不等于最大类别概率；当前分类不以它设门槛 |
| `usage.truncated` | 必须检查；true 表示题面并未完整输入，不能当作正常分类结果 |
| `usage.state_tokens_dropped` | 丢弃的题面 token 数 |
| `routing.model` | Router 实际选择的服务模型别名 |
| `routing.repo` | 实际加载的 checkpoint；判断是否为最终版本应看此字段 |

### 为什么请求和响应的 model 不同

请求的 `"model":"multilingual"` 是 **Router 的模型选择别名**，当前服务配置将这个别名映射到最终微调目录。

响应顶层 `"model":"laya-rl-agent"` 是 **推理引擎固定返回的通用标识**，不是请求别名或 checkpoint 版本。当前 `laya/agent.py` 的响应组装代码直接写入此字符串，并非由 checkpoint 的 `model_name` 推导。这不表示模型回退到其他 checkpoint，也不表示本次请求执行了强化学习。

客户端不要把请求 `model` 改为 `laya-rl-agent`，也不要用响应顶层 `model` 区分原始模型、fold-0 和最终模型；这些版本都可能返回同一个引擎标识。应检查 `routing.model` 和 `routing.repo`。

## 长度和置信度限制

总长度配置为 `max_len=1024`，任务头配置为 `head_max_len=256`。当前固定提示词和选项占用后，题面约可容纳 871 tokens，不能按字符数直接判断。原始 665 道题中两个超长题已从训练快照排除，原始题库未删除。

测试时遇到 `truncated=true`，应记录为“超长/无法完整分类”并交由上层处理；接口不提供第四个难度类别，也没有承诺自动过滤未知超长题。HTTP 异常、超时或缺少分类字段也不能默认当成简单。

最终模型温度为 1.0，没有独立校准数据。72.82% 是“简单”类别的分数，不是“有 72.82% 的概率分类正确”，更不是解题概率。本版本只按最高概率类别输出，不设旧版 0.7 或其他门槛。将来若需要按分类可靠性设置门槛，应使用未参与最终训练的新难度标注题校准并评估。

## 只评估难度分类准确性

Ground Truth 来自人工难度标签，压轴合并为困难。预测与难度标签一致才计为分类正确；解题模型是否答错不改变难度标签，也不用于评价当前分类器。

| 数据口径 | 分类准确率 | 宏平均召回率 |
|---|---:|---:|
| 20 轮方案的五折测试，663 道各测试一次 | 77.38% | 62.13% |
| 最终全量模型对训练题回放 | 90.95% | 93.07% |

第二行不是独立测试。不能拿两行的差值当作最终模型的泛化提升；全部题参与训练后，最终模型尚无新题独立测试成绩。类别不平衡时应同时看每类精确率、召回率、F1 和混淆矩阵，而不是只看总准确率。详见 [训练和分类指标](math-router-finetune.zh-CN.md)。

测试环境先固定本版本，不根据训练回放挑选新阈值或更换提示词。后续人工标注新题的简单/中等/困难标签，对照 `choice` 统计分类指标；训练题、历史五折测试和全新测试结果应分别记录。
