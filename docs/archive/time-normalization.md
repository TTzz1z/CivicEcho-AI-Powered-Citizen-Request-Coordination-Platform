# 时间表达标准化

工单同时保存原文与标准结果：occurred_at_text、occurred_at_start/end、occurred_at_precision、timezone。原文永不被标准值覆盖，数据库时间均为 timestamptz。

Action 读取 Duckling interval/instant 时传递带时区的开始、结束和精度；Backend 再校验时区与 `start < end`。没有结构化结果时，Backend 只解析经过测试的“昨天晚上”“N天前”“上周一”“最近一个月”。“前些日子”等表达不猜测，只存原文。

默认时区为 `Asia/Shanghai`，可通过环境变量配置。测试固定参考时间覆盖跨日、跨月/年和 UTC+8 边界，避免依赖测试执行当天。
