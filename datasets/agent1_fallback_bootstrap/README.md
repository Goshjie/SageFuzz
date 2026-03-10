# Fallback TaskSpec 初版数据集

这个目录放的是从现有运行结果中自动抽取出来的初版训练材料。
它更像“原始毛坯数据”，不是最终可直接训练的高质量数据集。

包含文件：

- `fallback_only.jsonl`
  只包含明确发生了 fallback 接管的样本

- `direct_only.jsonl`
  只包含同类任务家族中，`Agent1` 直接成功输出的样本

- `mixed.jsonl`
  将上面两类样本合并后的结果

- `summary.json`
  样本数量统计和家族分布

每条记录包含的主要字段：

- `prompt`
  便于 SFT 使用的输入文本

- `completion`
  目标 `TaskSpec` JSON 字符串

- `user_intent`
  原始用户意图

- `candidate_task`
  如果存在，表示主模型先给出的不完整或待修正 task

- `critic_feedback`
  如果存在，表示 review/fallback 阶段给出的修正依据

- `family`
  推断出的任务家族

- `source_kind`
  样本来源类型，例如 direct task 或 fallback task

推荐使用方式：

1. 先看 `fallback_only.jsonl`
   这部分最符合“外挂 fallback 小模型”的训练目标

2. 再少量加入 `direct_only.jsonl`
   只作为格式稳定和结构分布锚点，不建议喧宾夺主

3. 评估集不要从这里面随机切
   后续应该用外部同类型程序单独构造测试集

当前样本数量：

- `fallback_only`: 2
- `direct_only`: 118
- `mixed`: 120
