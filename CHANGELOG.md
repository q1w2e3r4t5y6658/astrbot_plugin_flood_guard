# 更新日志

本文件记录 **刷屏守卫 / Flood Guard**（`astrbot_plugin_flood_guard`）的全部版本变更。
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)，格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

> AstrBot 插件管理页会读取本文件展示更新日志（支持 `CHANGELOG.md` / `changelog.md` / `CHANGELOG` / `changelog`）。

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
