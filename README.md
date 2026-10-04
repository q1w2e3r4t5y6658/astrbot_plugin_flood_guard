# astrbot_plugin_flood_guard（刷屏守卫）

AstrBot 群刷屏检测与自动禁言插件。

默认是**条数模式**：统计窗口内**任意消息**的条数，达到阈值即触发禁言；
也可以切换成**复读机模式**（只统计「同一条消息」的重复），见 `/flood mode`。

阈值 / 窗口 / 禁言时长 / 播报文案，既可在**插件配置页**修改，也可由**群管理员在 QQ 群内**用命令对单个群单独覆盖。

> 语言约定：**插件命令为英文**；**说明文档与群内回复为中文**。

## 命令（单一扁平命令，英文）

群里直接发即可（**不强制 @ 机器人**；带唤醒前缀 `/` 也行）。私聊不响应。

| 命令 | 权限 | 作用 |
|---|---|---|
| `/flood` 或 `/flood status` | 所有人 | 查看本群生效配置（也能验证插件是否加载成功） |
| `/flood help` | 所有人 | 用法说明 |
| `/flood mode <same\|any>` | 管理员 | 检测模式：`same` 只统计同一条消息；`any` 统计任意消息条数 |
| `/flood limit <数字>` | 管理员 | 达到多少条触发禁言 |
| `/flood window <秒>` | 管理员 | 统计窗口长度 |
| `/flood mute <秒>` | 管理员 | 禁言时长 |
| `/flood notice <文案>` | 管理员 | 本群播报文案 |
| `/flood reset` | 管理员 | 清除本群覆盖，回退全局默认 |

示例：

```
/flood mode any
/flood limit 5
/flood window 5
/flood mute 600
/flood notice {at} 别复读了，禁言 {mute_text}
```

### 群内触发不依赖唤醒

AstrBot 在「未唤醒」时会直接终止事件（`waking_check` 阶段的 `event.stop_event()`），
这也是此前 `/flood` 在 QQ 群里偶尔无响应的原因。
现在命令**同时由群消息事件处理器兜底处理**：只要消息以 `/flood` 开头（后面可跟参数），
即使唤醒判定异常、没 @ 到机器人，也能正常响应；
若 AstrBot 已正常激活原生指令，则不会重复应答。

### 为什么用单一扁平命令

AstrBot 的**指令组 + 子指令**由框架预编译的指令树分发，且子指令处理器的过滤器在唤醒阶段会被跳过，导致触发不稳定、权限也可能失效。改成单一扁平命令 + 手动解析子命令后，跨版本可靠性高很多。

## 排障：群里发了命令没反应

1. **确认插件已加载。** 裸发 `/flood` 一定会返回状态；完全没反应说明插件没加载，去 AstrBot 日志里找 import 报错。
2. **版本门槛。** `metadata.yaml` 要求 `astrbot_version: ">=4.0,<5"`；版本不匹配会在启动前直接拒绝加载，请按你的实际版本调整该行。
3. **禁言没生效？** 机器人在该群必须是**群主或管理员**，否则腾讯会返回 `ERR_NOT_GROUP_ADMIN`。此时插件**不会在群里播报**，只在服务器日志留一条 WARNING：
   `[flood_guard] mute failed; group notice suppressed ...`

## 检测语义

| 配置 | 默认 | 行为 |
|---|---|---|
| `same_message_only` | `false` | `false`：窗口内任意消息计数；`true`：只统计「同一条消息」的重复 |
| `only_chat_messages` | `true` | 忽略撤回/管理变更/入群/戳一戳等 notice 事件 |
| `text_normalize` | `true` | 文本比对忽略大小写与空白 |

### 「同一条」如何判定（仅 `same` 模式）

对消息链里的**内容段**归一化生成签名，忽略 `Reply` 这类上下文段：

| 段类型 | 签名 |
|---|---|
| 文本 | 去空白 + 转小写 |
| 图片 / 语音 / 视频 / 文件 | 文件**内容签名**：≤1MB 做整文件 MD5；>1MB 取「文件大小 + 头/中/尾各约 170KB（合计 512KB）」 |
| 表情 | 表情 id |
| 卡片 / 分享 / 音乐 / 位置 | `data` |
| 戳一戳 | poke id |
| 合并转发 | 转发 id |

> 媒体必须走**内容签名**，不能拿路径或 URL：
> - AstrBot 会把图片下载到 `data/temp/media_image_<时间戳>_<随机>.jpg`，**路径每次都不同**；
> - QQ 的图片 CDN 链接形如 `.../download?appid=...&fileid=...&rkey=...`，其中 `rkey` 是**动态获取、会轮换的签名**，同一张图不同时刻拿到的 URL 可能不同。
>
> 拿路径或 URL 当签名，都会把「同一张图」判成不同消息，阈值永远凑不满。
>
> 采样策略：**≤1MB 整文件 MD5**（真实素材里约 91% 落在这一档，数学上精确）；**>1MB** 走「文件大小 + 头/中/尾各约 170KB（合计 512KB）」，避免为几十 MB 的视频做全量哈希。

多个段会拼接为 `a|b|c`，因此 `same` 模式下「同一句话 + 同一张图」才算同一条。

## 为什么禁言会有几秒延迟？

这是 **AstrBot 事件管道的固有延迟**，不是本插件的问题。一次真实触发的实测（群里 5 秒内连发 6 张图）：

| 环节 | 实测耗时 | 占比 |
|---|---|---|
| AstrBot 管道：事件派发 → 插件拿到消息 | **5.75 s** | 76% |
| 禁言接口往返（AstrBot → 适配器 → QQ） | **1.89 s** | 24% |
| **插件自身逻辑** | **0.005 s** | **0.07%** |

### 那 5.75 秒花在哪

AstrBot 处理每条消息都要依次走完这些阶段：

```
WakingCheck → WhitelistCheck → SessionStatusCheck → RateLimit
→ ContentSafetyCheck → PreProcess → ProcessStage（插件在这里）→ ...
```

**插件只能在 `ProcessStage` 运行**，前面每个阶段的耗时都会累加到触发时刻上。其中两个容易变慢的：

- **`WakingCheckStage`**：所有插件的过滤器都在这里逐条执行 —— 装的插件越多越慢；
- **会话限流**：`platform_settings.rate_limit` 按「用户 + 群」计数，超出后按 `strategy` 处理：
  - `discard`：**直接丢弃事件**（插件根本看不到这条消息，也就无法计数）；
  - `stall`：暂停整条流水线，等下一个时间窗口再继续（插件会被推迟）。

**所以插件不可能比「AstrBot 把消息交给它」更快。** 插件内部已做到几次内存字典操作（微秒级），继续优化插件没有意义。

### 想更快，只能从 AstrBot 侧下手

1. **减少该群上的插件数量**（或给该群关闭不用的插件），降低 `WakingCheckStage` 开销；
2. **调低 `max_messages`**：滞后对每条消息是固定的，阈值越低触发越早（例如 6 → 4，可早约 1~2 秒）；
3. 禁言接口那约 1.9 秒取决于「适配器 → QQ 服务端」，插件侧无法优化；
4. **检查 `rate_limit.strategy`**：若是 `discard`，繁忙群里超出限额的消息会被 AstrBot 丢掉，插件统计不到。

## 配置项

| 配置项 | 默认 | 说明 |
|---|---|---|
| `enabled` | true | 是否启用检测 |
| `same_message_only` | false | true=只统计同一条消息；false=统计任意消息条数 |
| `only_chat_messages` | true | 只统计聊天消息 |
| `window_seconds` | 5 | 统计窗口（秒） |
| `max_messages` | 6 | 达到多少条触发禁言（默认 5 秒 6 条即判定为刷屏） |
| `text_normalize` | true | 忽略大小写/空白 |
| `mute_seconds` | 600 | 禁言时长（秒），0 表示只计数不实际禁言 |
| `cooldown_seconds` | 30 | 同一用户触发后的冷却 |
| `notify` | true | 触发后是否播报 |
| `notify_template` | 见下 | 播报文案模板 |
| `manage_permission` | both | 谁可以改本群设置 |
| `manage_users` | [] | 额外可管理用户 ID |
| `exempt_group_admins` | true | 群主/群管理员豁免检测 |

> 豁免说明：插件**只有一个豁免**——群主 / 群管理员（刷屏类插件的通行做法，且机器人本身也禁言不了群主）。
> 不提供机器人管理员（AstrBot `admins_id`）豁免，也没有免检测白名单：只要不是群主/群管理员，谁刷屏都会计数、都会禁言。

默认播报文案：

```
{at} 你在 {window} 秒内发送了 {count} 条消息，达到刷屏阈值：{mute_text}。
```

`{mute_text}` 成功时为「已被禁言 10 分钟」这类文案；失败时不会播报（只记 WARNING 日志）。

占位符：`{at} {user} {user_id} {nickname} {group_id} {count} {window} {mute} {mute_text}`

## 平台支持

| 平台 | 禁言 | 说明 |
|---|---|---|
| `aiocqhttp`（OneBot v11 / NapCat 等） | ✅ | `event.bot.call_action("set_group_ban", ...)` |
| 其他平台 | ❌ | 仅计数；禁言失败时群里静默，日志留 WARNING；可在 `_mute()` 中扩展 |

## 安装

1. 把本仓库放到 `AstrBot/data/plugins/astrbot_plugin_flood_guard/`，或在 WebUI 从 zip 安装。
2. 在 WebUI 插件管理里启用并配置。
3. 确保机器人在目标群里是**群主或管理员**。

## License

MIT
