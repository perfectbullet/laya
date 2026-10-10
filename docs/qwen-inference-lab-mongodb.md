# QwenInferenceLab MongoDB 数据集合说明

本文说明 Laya 如需接入 QwenInferenceLab 的离线数学能力数据时，如何读取共享的 MongoDB。

当前难度三分类测试版本（2026-10-10）改用 `questions.difficulty` 作为目标标签，压轴归入困难；只输入 `questions.question`，不输入难度字段。该日题库快照为 665 道，过滤两个超长题后训练 663 道。`question_capabilities` 与正式 `evaluations` 仍只覆盖原来的 250 道，它们不是当前难度分类标签来源，也不用于评价分类是否正确。以下 capability-v1 说明与数量表保留为历史能力路由数据说明；当前接口见 [三分类测试环境说明](math-difficulty-test-api.zh-CN.md)。

> 这是一项**可选集成**，而不是 Laya 核心功能的依赖。Laya 的默认路由仍应可在本机、无外部服务时工作；不要在默认初始化、核心 API 或测试中强制连接该 MongoDB。

## 1. 连接与数据范围

数据库名为 `qwen_math_lab`。连接信息由部署环境提供，使用下列环境变量，不要将 URI、用户名或密码写入代码、文档样例或提交记录：

```text
MONGODB_URI                     # 若设置，优先使用
# 或者：
MONGODB_HOST
MONGODB_PORT                    # 默认 27017
MONGODB_DATABASE=qwen_math_lab
MONGODB_USERNAME                # 可选；与 PASSWORD 成对设置
MONGODB_PASSWORD
MONGODB_AUTH_SOURCE             # 可选；默认同 DATABASE
```

截至 2026-10-08，和 Qwen 数学能力实验有关的正式语料为：250 道题、750 次已评测运行（每题 3 次）。`runs` 集合当前有更多历史运行记录，**不能**以 `runs` 的总记录数作为该实验样本数。

## 2. Laya 应读取的集合

Laya 若仅需要“这道题是否适合交给本地 Qwen3.6-35B-A3B”的历史参考语料，应使用下面三个集合，并固定版本过滤条件。

| 集合 | 当前数量 | 推荐过滤 | 用途 |
|---|---:|---|---|
| `questions` | 250 | `id` 与下方 `questionId` 对应 | 原始题面及人工元数据 |
| `question_capabilities` | 250 | `capabilityVersion: "capability-v1"` | 每题三次运行聚合出的能力标签 |
| `question_embeddings` | 500 | `embeddingVersion: "qwen3-embedding-0.6b-v1"` | 250 条 Qwen3-Embedding-0.6B 向量；另 250 条为旧 BGE 版本，不要混用 |

三者的关联键为：

```text
questions.id
  = question_capabilities.questionId
  = question_embeddings.questionId
```

读取前应验证：三个版本化查询均返回 250 条、`questionId` 唯一且集合完全一致；`question_embeddings.dimension` 全部为 `1024`。

## 3. 核心字段

### `questions`

```json
{
  "id": "MATH-001",
  "question": "题目文本",
  "reference_answer": "参考答案（敏感标签，路由输入不要使用）",
  "tag": "...",
  "difficulty": "...",
  "math_type": "...",
  "grade": "...",
  "source": "...",
  "image_path": "...",
  "reference_answer_image_path": "..."
}
```

`question` 是允许送入 embedding 的唯一题目内容。`reference_answer`、参考答案图片、任何模型回答或推理文本不得作为路由特征或 embedding 输入，避免标签泄漏。

### `question_capabilities`

```json
{
  "questionId": "MATH-001",
  "capabilityVersion": "capability-v1",
  "evaluatorPipelineVersion": "evaluator-v1",
  "question": "题目文本",
  "tag": "...",
  "mathType": "...",
  "difficulty": "...",
  "attempts": 3,
  "gradableAttempts": 3,
  "mathCorrect": 2,
  "mathIncorrect": 1,
  "review": 0,
  "unresolved": 0,
  "runtime": {"completed": 3, "truncated": 0, "failed": 0, "cancelled": 0, "interrupted": 0},
  "runtimeSuccessRate": 1.0,
  "mathPassRate": 0.6666667,
  "localSuccessCount": 2,
  "localSuccessRate": 0.6666667,
  "labelUsable": true,
  "attemptDetails": [],
  "createdAt": "...",
  "updatedAt": "..."
}
```

路由实验的标签规则如下：

```text
labelUsable == true 且 localSuccessRate == 1.0  => safeLocal = true
labelUsable == true 且 localSuccessRate <  1.0  => safeLocal = false
labelUsable == false                            => 标签未知；不参与精度、召回率等 Ground Truth 指标
```

`mathType`、`difficulty`、`tag` 仅用于结果分组与诊断；当前 Router 不将它们作为决策特征。`attemptDetails` 用于审计每次运行和评测来源，不是在线检索的必要字段。

### `question_embeddings`

```json
{
  "questionId": "MATH-001",
  "embeddingVersion": "qwen3-embedding-0.6b-v1",
  "model": "Qwen/Qwen3-Embedding-0.6B",
  "baseUrl": "http://.../v1",
  "dimension": 1024,
  "textHash": "sha256(question)",
  "embedding": [0.0123, -0.0456],
  "question": "题目文本",
  "tag": "...",
  "mathType": "...",
  "difficulty": "...",
  "capabilityVersion": "capability-v1",
  "localSuccessRate": 1.0,
  "mathPassRate": 1.0,
  "labelUsable": true,
  "createdAt": "...",
  "updatedAt": "..."
}
```

`embedding` 是 1024 维浮点数组。`textHash` 用来判断题面变更后向量是否过期。推荐把 `question_capabilities` 作为能力标签的权威来源；嵌入记录中重复保存的成功率和标签是导出时的 metadata，不应覆盖 capability 记录。

## 4. 其他集合：作用与使用边界

| 集合 | 当前数量 | 用途 | Laya 接入建议 |
|---|---:|---|---|
| `evaluations` | 750 | Evaluator 对单次 run 的正式机器评测 | 仅审计或重建 capability；以 `(runId, pipelineVersion)` 唯一 |
| `runs` | 2,006 | 推理运行原始请求、回答、耗时及旧 `evaluation` 字段 | 高敏感/高体积审计数据；不要把 `runs.evaluation` 当 Ground Truth |
| `question_gold_profiles` | 250 | 参考答案解析与评测路由配置 | Evaluator 内部使用；不作为 Router 输入 |
| `router_predictions` | 0 | Web 影子测试的路由预测日志 | 可选读取做运营分析；当前为空 |
| `model_configs` | 8 | 推理/评审模型连接配置 | 不向客户端返回，可能含服务端连接信息 |
| `model_settings` | 1 | 当前选择的模型配置 | 管理界面状态，不是能力数据 |
| `inference_benchmark` | 11 | 通用推理基准历史数据 | 与本次 250 题 Router 语料分离 |
| `qwen36_ab_benchmark_20260921` | 4 | 2026-09-21 的 Qwen3.6 A/B 基准 | 历史分析用途 |

## 5. 索引与查询示例

已存在的唯一索引：

```text
questions:              (id)
evaluations:            (runId, pipelineVersion)
question_gold_profiles: (questionId, adapterVersion)
question_capabilities:  (questionId, capabilityVersion)
question_embeddings:    (questionId, embeddingVersion)
router_predictions:     (predictionId)
```

最小只读查询（Mongo shell 形式）：

```javascript
const capabilities = db.question_capabilities.find(
  { capabilityVersion: "capability-v1" },
  { _id: 0, questionId: 1, question: 1, localSuccessRate: 1, labelUsable: 1 }
).toArray();

const embeddings = db.question_embeddings.find(
  { embeddingVersion: "qwen3-embedding-0.6b-v1" },
  { _id: 0, questionId: 1, dimension: 1, textHash: 1, embedding: 1 }
).toArray();
```

Laya 若只需计算相似度，应在服务端将两者按 `questionId` join，并使用同一 embedding version 的向量计算 cosine similarity。不得把不同版本的向量放在同一检索集合中。

## 6. `router_predictions` 日志格式

当前 Web 影子页经 QwenInferenceLab server 写入该集合。记录包含：

```json
{
  "predictionId": "uuid",
  "question": "用户输入题目",
  "questionId": "可选；存在时用于检索时排除自身",
  "profile": "development | conservative",
  "decision": "local | cloud",
  "score": 1.0,
  "features": {"top1Similarity": 0.9, "weightedSuccess": 1.0},
  "neighbors": [],
  "reasonCodes": [],
  "policyConfig": {},
  "embeddingVersion": "qwen3-embedding-0.6b-v1",
  "routerVersion": "router-v1",
  "textHash": "sha256(question)",
  "durationMs": 0,
  "createdAt": "..."
}
```

这是实验日志，包含用户题目文本。接入方应设置访问控制与数据保留策略；它不能当作模型真实正确性的标签，除非后续另行回填人工或自动评测结果。

## 7. 数据质量与当前结论

当前 capability 数据由每题 3 次运行聚合而来：250 题中 240 题 `labelUsable=true`，另 10 题的标签未知。240 个可用标签中，220 题为 `safeLocal=true`（3/3 成功），20 题为 `safeLocal=false`（0/3、1/3 或 2/3）。

这些数据适合用于离线检索、影子路由和诊断；它们不是独立的新题测试集。对未见新题的泛化表现，仍应通过新增、未参与上述 250 题构建的 holdout/shadow 题集验证。
