# bind.md · qiqi-dream-swarm

## Resource Constraints

| 约束 | 值 |
|:--|:--|
| max_parallel_teammates | 1（串行四相流水线；评分闸门可被宿主单独复用） |
| total_wall_clock_budget | 30 分钟（不含宿主为 REM/海马安排的 LLM+KG 时间） |
| total_token_budget | 确定性阶段（01/02/03）不消耗 LLM token；04/05 由宿主提供 |

## Behavioral Constraints

- 评分官是闸门角色：只按阈值判 eligible，不受上游希望「多留几条」的压力影响；
- 轻梦官只做浅层整理，不做语义重组；
- REM/海马需要真实模型与 KG 引擎，缺失时输出 needs_llm 且 outputs 为空，绝不编造重组或图谱；
- 淘汰（cascade）必须给出理由字段，不得静默丢弃。

## Failure Handling

- 角色超时/输出不合规：重试 1 次，仍失败则报告如实标记；
- 评分官 eligible_count=0：整轮如实输出「无晋升候选」，不继续后续阶段；
- 04/05 needs_llm：交付物为前段可计算产物 + 交接包，重组与固化由宿主补做；
- 输入超规模（记忆条目 > 5000）：先分批跑轻梦+评分，汇总后再进深梦，如实标注批次。
