---
name: morari-timer-session-debt-correction
description: Use when a morari timer 计时器类应用的 session 因忘记停止（手機鎖屏、忘記點停止）而记录了错误的结束时间，需要在数据库层手动修正 session 时长、debt（连续用眼债务）与 daily 统计、phase 状态时。适用于带「连续使用上限 + 债务」机制的计时系统（如 agent_manager 项目）。
---

# Timer Session Debt Correction

## 何时用

Session 因未正常停止，`ended_at` 远晚于实际结束时间（例如使用者说「工作其实 1:50 就结束了，但系统显示 7:09」）。需要修正该 session，并连带修正由它衍生出的统计与状态。

**症状**：`duration_sec` 异常长、`debt_sec` 异常大、`timer_state.phase = 'daily_done'`（但实际今日用眼远未超标）。

## 核心原理（LLM 不会直接知道，需先读 timer_service.py 确认）

这类系统通常不是单纯把 session 时长加总，而是用「连续用眼时间」对照阈值滚动计算债务：

- **screen 类型（如工作）**：
  `previous_overage = max(0, continuous_screen_sec_前 - threshold)`
  `continuous_screen_sec += elapsed`
  `new_overage = max(0, continuous_screen_sec - threshold)`
  `added_debt = max(0, new_overage - previous_overage)`
  `accumulated_debt_sec += added_debt`；该 session 的 `debt_sec = added_debt`

- **系统类非screen类型（如休息，is_system=true）**：
  `surplus = max(0, elapsed - interval_minutes*60)`
  `accumulated_debt_sec = max(0, accumulated_debt_sec - surplus)`（休息会还债）
  `continuous_screen_sec` 重置为 0

- **其他非screen类型（如睡觉）**：只累加 `daily_non_screen_sec`，不影响 debt，也会重置 continuous_screen_sec

`phase` 变成 `daily_done` 的条件是 `daily_screen_sec + elapsed >= daily_limit_minutes*60`。一旦某个 session 时长被错误地拉长（计时器没停），会连环导致：该 session 的 debt 暴增 → accumulated_debt_sec 暴增 → daily_screen_sec 暴增 → phase 被误判为 daily_done。

## 修正步骤

1. **找出问题 session**：按 user/日期查最近 session，`duration_sec` 与「使用者说的实际结束时间」对不上的就是它。
2. **问清实际结束时间**，改写 `ended_at`、重算 `duration_sec`。
3. **重算该 session 的 debt_sec**：找到它之前最近一个「会重置 continuous_screen_sec」的 session（休息/睡觉等非screen类型）作为起点，用上面公式重算 overage/debt。修正后通常远小于原值（甚至为 0）。
4. **重算当日 daily_screen_sec / daily_non_screen_sec**：直接对当地时区当日所有 session 按 `counts_screen_time` 分组重新 SUM，不要用算术减法去猜（容易漏算时区边界）。
5. **重算 accumulated_debt_sec**：从当日 00:00（或上次 daily reset）开始，按时间顺序重放每个 session 的公式，得到当前应有的债务值。
6. **修正 `timer_state.phase`**：若新的 daily_screen_sec 远低于上限，改回 `idle`（不要保留 `daily_done`）。同时更新 `updated_at` 为修正后的实际结束时间。
7. 全程包在一个事务（`BEGIN...COMMIT`）内执行，执行后立即 SELECT 验证。

## 常见坑

- 数据库存 UTC，需用 `AT TIME ZONE '<当地时区>'` 转换后再判断「今天」的范围，否则跨日时段会算错。
- 不要只对 accumulated_debt_sec 做简单的「原值 - (原session debt - 新session debt)」减法 —— 如果中间还有其他 session 的债务增减，这样算会错；按时间顺序重放才准确。
- 修正一个 session 后，记得检查它后面是否还有依赖它结束时间的新 session（例如新增的睡觉 session），避免时间重叠。
