# Agent1 Fallback 预览数据集

这个目录放的是一个很小的可读预览集，目的不是直接拿去训练，
而是让你先看清楚：

- 一条训练样本包含哪些字段
- `candidate_task` 和 `target_task` 分别表示什么
- `critic_feedback` 在数据里是怎么出现的
- 这个小模型为什么更像“外挂 fallback”，而不是“替代主 Agent1”

当前包含的样本类型：

- `repair_from_feedback`
  主 `Agent1` 已经产出了一个不稳定或不完整的任务，
  后续又通过 review/fallback 修正成了可执行 `TaskSpec`

- `fallback_from_intent`
  主模型没有稳定收敛，系统直接根据原始意图合成了 fallback `TaskSpec`

- `direct_anchor`
  同一任务家族中的高质量直接样本，用来做格式锚点或少量辅助监督

文件说明：

- `preview.pretty.json`
  便于人工阅读的格式化 JSON，建议你先看这个

- `preview.jsonl`
  一行一条 JSON 记录，适合后续脚本处理

样本数量：

- `4`
