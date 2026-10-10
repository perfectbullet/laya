# 微调 API 索引（中文）

译自 [英文 API 索引](train.md)。原文使用文档构建器自动展示 Python 的函数签名和说明；以下保留相同的 API 入口。自动生成的 docstring 仍以源码语言展示，中文训练流程见 [微调指南](../finetune.zh-CN.md)。

`laya.train` 需要单独导入，例如 `from laya.train import finetune, TrainConfig`，它没有从顶层包重新导出。命令行入口为 `laya-train`。

## 执行微调

::: laya.train.TrainConfig

::: laya.train.finetune

::: laya.train.dry_run

## finetune 的训练与校准环节

::: laya.train.train_model

::: laya.train.calibration_records

::: laya.train.calibration_report

## 读取数据

::: laya.train.read_data

::: laya.train.rows_from_csv

## 构建训练样本

::: laya.train.items_from_rows

::: laya.train.target_from_gold

::: laya.train.target_from_expected

::: laya.train.to_internal

::: laya.train.make_item

::: laya.train.encode_item

::: laya.train.draw_option_order

::: laya.train.split_calibration

## 损失函数

::: laya.train.soft_ce_loss

::: laya.train.rlcd_loss

## Checkpoint 解析、加载与保存

::: laya.train.resolve_checkpoint_dir

::: laya.train.load_checkpoint

::: laya.train.save_checkpoint
