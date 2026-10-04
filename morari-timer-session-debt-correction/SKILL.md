---
name: morari-timer-session-debt-correction
description: Use when a morari timer 计时器类应用（agent_manager 项目）的 session 因忘记停止（手機鎖屏、忘記點停止）而记录了错误的结束时间，需要在数据库层手动修正 session 时长、debt（连续用眼债务）、daily 统计、phase 状态；也适用于事后需要补记多段遗漏的活动（如睡觉、吃饭）并把当前正在进行的 session 与 timer_state「指针」（current_session_id / phase_started_at 等）接续上的情境。
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

## 情境 B：还需要补记后续多段活动，并接上「现在正在进行」的 session

用户常见说法：「~1:30 娱乐 睡觉 1:30~11:10 11:50 吃饭开始」——即：坏掉的 session 实际在 1:30 结束，之后睡到 11:10，11:50 开始吃饭（现在还在吃）。这时情境 A 的第 6 步「改回 idle」不适用，要改成把 timer_state 接到新建的、仍在进行中的 session 上。

在情境 A 步骤 1-5 的基础上，额外做：

1. **修正坏掉的 session**：`ended_at` 改为用户说的实际结束时间，`duration_sec`、`debt_sec` 按公式重算（通常上一个 session 是休息/系统类，continuous_screen_sec 从 0 起算）。
2. **按时间顺序补插入后续每一段活动为独立 session**：`started_at` 必须等于前一段的 `ended_at`（不要留错位的时间戳，避免重叠或空隙是错的）。查 `session_types` 表按 `user_id` 找到对应类型的 `id`（如「睡觉」「吃饭」），注意同名类型在多用户/多次创建下会有很多个 id，一定要带 `user_id` 过滤。
3. **最后一段如果用户说「现在还在进行」**：该 session 的 `ended_at`/`duration_sec` 留 `NULL`，`state='active'`。
4. **重放当日全部 session（含新补的）算出 daily_screen_sec / daily_non_screen_sec / accumulated_debt_sec**：正在进行中的最后一段 session 不计入（它还没 finish，对应字段只在 finish 时才累加）。
5. **同步「指针」，即 `timer_state` 表**：这是前端时钟指针/当前进度显示的唯一依据，光改 `sessions` 表不会让前端正确显示。需要一并更新：
   - `phase = 'active'`（不是 `idle`，因为有进行中的 session）
   - `current_session_id` / `current_type_id` 指向新建的进行中 session
   - `phase_started_at` = 该 session 的 `started_at`（这就是「指针」的起算点，前端用它 + 服务器当前时间算已过秒数）
   - `elapsed_before_pause_sec = 0`（除非该 session 本身有暂停记录）
   - `continuous_screen_sec`：如果最后一个已完成的 session 是「非 screen 类型」（休息/睡觉等），会重置为 0；否则要继续累加。
   - `updated_at = now()`

## 常见坑

- 数据库存 UTC，需用 `AT TIME ZONE '<当地时区>'` 转换后再判断「今天」的范围，否则跨日时段会算错。
- 不要只对 accumulated_debt_sec 做简单的「原值 - (原session debt - 新session debt)」减法 —— 如果中间还有其他 session 的债务增减，这样算会错；按时间顺序重放才准确。
- 修正一个 session 后，记得检查它后面是否还有依赖它结束时间的新 session（例如新增的睡觉 session），避免时间重叠。
- `session_types` 表是多用户共用的，同一个名字（如「娱乐」「睡觉」「吃饭」）会有很多个不同 `id`，务必用 `user_id` 过滤，不要凭名字猜 id。
- 「指针」不是比喻——前端时钟动画就是靠 `timer_state.phase_started_at` + `elapsed_before_pause_sec` 计算的，只改 `sessions` 表不改 `timer_state` 的话数据库对了但界面还是错的。
- 用户描述的时间段之间若有空档（例如睡醒到开始吃饭中间空 40 分钟）且用户没提那段在做什么，不要自行编造 session 去填补，留空即可。
