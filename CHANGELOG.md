# 更新日志

本文件记录 **刷屏守卫 / Flood Guard**（`astrbot_plugin_flood_guard`）的全部版本变更。
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)，格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

> AstrBot 插件管理页会读取本文件展示更新日志（支持 `CHANGELOG.md` / `changelog.md` / `CHANGELOG` / `changelog`）。

---

## [0.7.1] - 2026-10-05

### 变更
- `same` 模式下**大文件（>1MB）的内容签名采样预算从 24KB 提升到 512KB**（头 / 中 / 尾各约 170KB），进一步降低大文件被误判为「同一条」的概率；`≤1MB` 仍走整文件 MD5。

### 文档
- README 新增 **「为什么禁言会有几秒延迟？」**，用实测数据交代延迟来源（一次真实触发）：

  | 环节 | 实测 | 占比 |
  |---|---|---|
  | AstrBot 管道（事件派发 → 插件拿到消息） | **5.75 s** | 76% |
  | 禁言接口往返（AstrBot → 适配器 → QQ） | **1.89 s** | 24% |
  | 插件自身逻辑 | **0.005 s** | 0.07% |

  并说明：插件只能在 `ProcessStage` 运行，前面 `WakingCheck → … → PreProcess` 各阶段的耗时都会累加到触发时刻；`WakingCheckStage` 要跑所有插件的过滤器，会话限流 `rate_limit` 的 `discard` 策略还会直接丢掉事件（插件根本看不到）。
  可执行的提速方向：减少该群插件数量、调低 `max_messages`、检查 `rate_limit.strategy`。
- README 澄清**媒体签名为什么必须基于内容**：QQ 图片 CDN 链接带动态轮换的 `rkey` 签名，AstrBot 又会把图下载到随机临时路径 —— 拿 URL/路径当签名会把「同一张图」判成不同消息。

---

## [0.7.0] - 2026-10-04

### 变更（影响行为）
- **默认阈值下调**：`max_messages` 默认 `10 → 6`（窗口仍 5 秒）——「5 秒内 6 条」即判定为刷屏。
- **媒体签名改为混合策略**（仅影响 `same` 模式）：
  - `≤ 1MB` → **整文件 MD5**（真实素材里 91% 落在这一档，数学上精确，无碰撞可能）
  - `> 1MB` → `文件大小 + 头/中/尾 各 8KB`（合计 24KB，开销固定）
  - 实测 839 个真实素材：**0 误判 / 0 漏判**；平均 0.408 ms/文件（整文件 0.945 ms），7.3MB 视频 0.14 ms（整文件 20 ms，**约 143 倍**）
  - 为什么必须基于内容：QQ 图片 CDN 链接带 **rkey 签名且会轮换**，同一张图的 URL 每次可能不同；AstrBot 又会把图下载到**随机临时路径** —— 拿 URL/路径当签名会把「同一张图」判成不同消息。

### 修复
- **`same` 模式下「无签名消息」漏检**：AstrBot 会把 `mface`（商城大表情）等消息段直接丢弃，这类消息签名列表为空、`key` 为空串，插件随即 `return` —— **完全不计数**。现统一归为 `EMPTY_KEY`，照常参与计数。

### 性能
- **达标后第一件事就是禁言**：冷却写入挪到禁言之后，禁言路径上不留多余动作。
- **禁言接口加 8 秒超时**（`MUTE_CALL_TIMEOUT`）：此前无超时，平台 API 卡住会拖死整个事件循环。
- **禁言失败改为 5 秒短冷却**（`MUTE_RETRY_COOLDOWN`）并尽快重试：此前失败也吃满完整冷却，表现为「还在刷却一直不管」。
- **触发后 `event.stop_event()`**：刷屏消息不再进入后续流程（如 LLM 回复），减轻负载。
- 「任意消息」模式热路径：**不遍历消息段、不查数据库、不读文件、不算 MD5、不创建协程**。

### 文档
- 新增 `CHANGELOG.md`。

---

## [0.6.6] - 2026-10-04

### 性能
- **省掉每条群消息一次数据库查询**：`_effective_cfg()` 增加 30 秒内存缓存（`/flood` 写操作与 `/flood reset` 会立即失效）。此前**每条群消息**都会 `get_kv_data()` 查一次 KV。
- **冷却检查提前**：先做纯内存的冷却判断，再取配置——冷却中的用户不再触发任何后续工作。
- **媒体哈希移出事件循环**：`same` 模式下图片 / 视频的 MD5 改用 `asyncio.to_thread` 在线程池执行，不再阻塞事件循环。
- 大文件哈希阈值 32MB → 4MB（超过则只采样首尾 1MB，减少磁盘 I/O）。

### 说明
- 默认的「任意消息」模式热路径开销：**不遍历消息段、不查数据库、不读文件、不算 MD5**，仅做几次内存字典操作。

---

## [0.6.5] - 2026-10-04

### 修复
- **`/flood mode` 的群级覆盖不生效**：`_message_key()` 原先读取全局配置，导致「全局 any + 某群设为 same」时该群仍按 any 计数。现改为读取**生效配置**（含群级覆盖）。
- **日志与实际检测不一致**：日志曾输出 `mode=same`，实际却按 any 计数；现在模式判断与日志共用同一份生效配置。

### 说明
- 确认「任意消息」模式（`same_message_only = false`）**不遍历消息段、不读本地文件、不计算 MD5**，是资源开销最低的路径；MD5 仅在 same 模式下对图片 / 语音 / 视频 / 文件计算。

---

## [0.6.4] - 2026-10-03

### 修复
- 统一 `same_message_only` 的默认值：`_conf_schema.json`、代码 fallback、README、i18n **全部对齐为 `false`**（此前代码 fallback 误写为 `true`，与文档矛盾）。
- 修正模块文档字符串：说明默认「按条数」模式、补齐 `/flood mode` 指令、去掉过时的「必须唤醒」说明。

---

## [0.6.3] - 2026-10-03

### 变更
- `metadata.yaml` 的 `author` 由 `MeowAndy` 更正为 `q1w2e3r4t5y6658`（⚠️ `plugin_id` 随之变更）。

### 文档
- 修正 README 与中英 i18n 中一批与实际行为不符的描述（默认模式、指令名、图片签名算法、默认播报文案等）。
- 修复 `/flood status` 显示的模式不随本群覆盖变化的问题。

---

## [0.6.2] - 2026-10-03

### 移除
- 移除 `whitelist`（全局免检测白名单）。此后插件**只剩一个豁免：群主 / 群管理员**。

---

## [0.6.1] - 2026-10-03

### 新增
- 恢复 `exempt_group_admins`（群主 / 群管理员豁免检测，默认开启）——刷屏类插件的通行做法，且机器人在 QQ 里本身也禁言不了群主。

---

## [0.6.0] - 2026-10-03

### 移除
- 移除 `exempt_admins`（机器人管理员豁免）与 `exempt_group_admins`，不再提供任何按身份的免检测后门。

---

## [0.5.4] - 2026-10-03

### 变更
- 禁言失败时**不再在群里播报**，改为写一条 WARNING 日志（避免「已被禁言（禁言失败）」这类自相矛盾的提示）。
- 私聊不再响应 `/flood`（静默忽略）。

---

## [0.5.3] - 2026-10-03

### 文档
- README 与 i18n 文案修正，与当前实际行为对齐。

---

## [0.5.2] - 2026-10-03

### 修复
- **图片 / 视频签名改为文件内容 MD5**：AstrBot 会把媒体下载到 `data/temp/media_image_<时间戳>_<随机>`，路径每次都不同；原先拿路径当签名，会导致「同一张图」被判成不同消息，永远凑不满阈值。

### 新增
- 默认改为**「按条数」模式**（`same_message_only = false`）：窗口内任意消息达到阈值即触发。
- 新增 `/flood mode <same|any>`，可按群切换检测模式。

---

## [0.5.1] - 2026-10-03

### 修复
- 群主 / 群管理员豁免判断被放在了命令兜底**之前**，导致群管理员自己发 `/flood` 反而被跳过。现将命令处理提到豁免判断之前（豁免只应作用于刷屏检测）。

---

## [0.5.0] - 2026-10-03

### 修复
- **QQ 群内命令无法触发**：AstrBot 在「未唤醒」时会直接终止事件（`waking_check` 阶段的 `event.stop_event()`）。现在 `/flood` 命令**同时由群消息事件处理器兜底执行**，不再依赖唤醒前缀 / @机器人 / CommandFilter；原生指令已激活时不会重复应答。

---

## [0.4.3] - 2026-10-03

### 变更
- 按 AstrBot 插件市场规范整理 `metadata.yaml`：补充 `support_platforms` 与 `tags`。

---

## [0.4.2] - 2026-10-03

### 文档
- **说明文档与群内回复改为中文**，命令保持英文。

---

## [0.4.1] - 2026-10-03

### 变更
- 移除中文命令别名，命令统一为**纯英文**。

---

## [0.4.0] - 2026-10-03

### 修复
- **命令触发不稳定**：AstrBot 的指令组 + 子指令在唤醒阶段会跳过子指令过滤器。改为**单一扁平命令** `/flood` + 手动解析子命令。
- 放宽版本门槛为 `astrbot_version: ">=4.0,<5"`（原先 `>=4.16,<5` 会在加载前被拒）。

---

## [0.3.0] - 2026-10-03

### 修复
- **权限分割**：所有修改类指令改为**显式校验**，普通群友无法再修改设置。不依赖框架的 `PermissionType.ADMIN`（它只认全局 `admins_id`，且子指令过滤器会被跳过）。

### 新增
- `manage_permission`：both / group_admin / astrbot_admin / everyone
- `manage_users`：额外可管理本群设置的用户 ID
- `exempt_group_admins`：群主 / 群管理员豁免检测

---

## [0.2.0] - 2026-10-03

### 变更
- 检测语义改为**「同一条消息重复触发」**（复读机模式，可关闭）。

### 新增
- `only_chat_messages`：过滤撤回 / 管理变更 / 入群 / 戳一戳等 notice 噪声
- `text_normalize`：文本比对忽略大小写与空白

---

## [0.1.0] - 2026-10-03

### 新增
- 首个版本：群刷屏检测与自动禁言
- 全局配置页 + 单群指令覆盖
- 播报文案可自定义

---

[0.7.1]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_flood_guard/releases/tag/v0.7.1
[0.7.0]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_flood_guard/releases/tag/v0.7.0
[0.6.6]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_flood_guard/releases/tag/v0.6.6
[0.6.5]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_flood_guard/releases/tag/v0.6.5
[0.6.4]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_flood_guard/releases/tag/v0.6.4
[0.6.3]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_flood_guard/releases/tag/v0.6.3
[0.6.2]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_flood_guard/releases/tag/v0.6.2
[0.6.1]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_flood_guard/releases/tag/v0.6.1
[0.6.0]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_flood_guard/releases/tag/v0.6.0
[0.5.4]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_flood_guard/releases/tag/v0.5.4
[0.5.3]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_flood_guard/releases/tag/v0.5.3
[0.5.2]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_flood_guard/releases/tag/v0.5.2
[0.5.1]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_flood_guard/releases/tag/v0.5.1
[0.5.0]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_flood_guard/releases/tag/v0.5.0
[0.4.3]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_flood_guard/releases/tag/v0.4.3
[0.4.2]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_flood_guard/releases/tag/v0.4.2
[0.4.1]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_flood_guard/releases/tag/v0.4.1
[0.4.0]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_flood_guard/releases/tag/v0.4.0
[0.3.0]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_flood_guard/releases/tag/v0.3.0
[0.2.0]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_flood_guard/releases/tag/v0.2.0
[0.1.0]: https://github.com/q1w2e3r4t5y6658/astrbot_plugin_flood_guard/releases/tag/v0.1.0
