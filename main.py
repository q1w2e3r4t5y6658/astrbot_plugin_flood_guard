"""astrbot_plugin_flood_guard —— 群刷屏检测与自动禁言。

检测语义：
- 默认「复读机模式」：**同一条内容**在窗口内重复达到阈值才触发（same_message_only=true）。
- 可切换「条数模式」：窗口内任意消息达到阈值即触发（same_message_only=false）。
- 「同一条」的判定：对消息链里的内容段做归一化签名（文本去空白/大小写、图片取 file/url、
  表情取 id、卡片取 data、合并不参与签名等），忽略 Reply 这类上下文段。

配置来源：全局插件配置页（_conf_schema.json）+ 单群 KV 覆盖（/刷屏 指令）。
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections import defaultdict, deque

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.event.filter import EventMessageType, PermissionType
from astrbot.api.star import Context, Star, register

try:  # 捕获指令剩余全部文本（AstrBot 提供）
    from astrbot.core.star.filter.command import GreedyStr
except Exception:  # pragma: no cover - 兼容旧版本，实际文本由 _extract_remainder 兜底
    class GreedyStr(str):
        """旧版本回退占位类型。"""


PLUGIN_ID = "astrbot_plugin_flood_guard"
KV_PREFIX = "group_cfg:"
ANY_KEY = "__any__"
DEFAULT_TEMPLATE = (
    "{at} 你在 {window} 秒内发送了 {count} 条相同消息，达到阈值，已被禁言 {mute_text}。"
)
# 可被单群覆盖的键
OVERRIDE_KEYS = ("window_seconds", "max_messages", "mute_seconds", "notify_template")
# 不参与「相同消息」签名的上下文段
IGNORED_SEGMENTS = {"Reply"}


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [p.strip() for p in str(value).replace("，", ",").split(",") if p.strip()]


def human_duration(seconds: int) -> str:
    seconds = max(0, _as_int(seconds, 0))
    if seconds == 0:
        return "0 秒"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days} 天")
    if hours:
        parts.append(f"{hours} 小时")
    if minutes:
        parts.append(f"{minutes} 分钟")
    if secs and not days:
        parts.append(f"{secs} 秒")
    return "".join(parts) or f"{seconds} 秒"


@register(
    PLUGIN_ID,
    "MeowAndy",
    "群刷屏检测与自动禁言：同一条消息重复触发，全局 + 单群阈值，可自定义播报文案",
    "v0.2.0",
)
class FloodGuardPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        # group_id -> user_id -> { 内容签名: deque[monotonic 时间戳] }
        self._hits: dict[str, dict[str, dict[str, deque]]] = defaultdict(
            lambda: defaultdict(dict)
        )
        # (group_id, user_id) -> 冷却截止时间
        self._cooldown: dict[tuple[str, str], float] = {}
        self._cleanup_task: asyncio.Task | None = None
        self._ensure_cleanup()

    def _ensure_cleanup(self) -> None:
        """惰性启动后台清理任务，保证创建时存在运行中的事件循环。"""
        if self._cleanup_task and not self._cleanup_task.done():
            return
        try:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        except RuntimeError:
            self._cleanup_task = None

    # ------------------------------------------------------------------ #
    # 配置读取
    # ------------------------------------------------------------------ #
    def _global_cfg(self) -> dict:
        return {
            "window_seconds": max(1, _as_int(self.config.get("window_seconds"), 5)),
            "max_messages": max(1, _as_int(self.config.get("max_messages"), 10)),
            "mute_seconds": max(0, _as_int(self.config.get("mute_seconds"), 600)),
            "cooldown_seconds": max(0, _as_int(self.config.get("cooldown_seconds"), 30)),
            "notify_template": str(self.config.get("notify_template") or DEFAULT_TEMPLATE),
        }

    async def _effective_cfg(self, group_id: str) -> dict:
        cfg = self._global_cfg()
        override = await self.get_kv_data(KV_PREFIX + str(group_id), None)
        if isinstance(override, dict):
            for key in OVERRIDE_KEYS:
                value = override.get(key)
                if value not in (None, ""):
                    cfg[key] = value
        cfg["window_seconds"] = max(1, _as_int(cfg["window_seconds"], 5))
        cfg["max_messages"] = max(1, _as_int(cfg["max_messages"], 10))
        cfg["mute_seconds"] = max(0, _as_int(cfg["mute_seconds"], 600))
        return cfg

    async def _update_group(self, group_id: str, key: str, value) -> dict:
        override = await self.get_kv_data(KV_PREFIX + group_id, None)
        if not isinstance(override, dict):
            override = {}
        override[key] = value
        await self.put_kv_data(KV_PREFIX + group_id, override)
        return override

    # ------------------------------------------------------------------ #
    # 「相同消息」签名
    # ------------------------------------------------------------------ #
    def _normalize_text(self, text: str) -> str:
        if bool(self.config.get("text_normalize", True)):
            return re.sub(r"\s+", "", text).lower()
        return text

    def _component_sig(self, comp) -> str | None:
        ctype = getattr(comp, "type", None)
        name = str(getattr(ctype, "value", ctype) or "")
        if name in IGNORED_SEGMENTS:
            return None
        if name == "Plain":
            return "t:" + self._normalize_text(str(getattr(comp, "text", "") or ""))
        if name == "Image":
            ident = (
                getattr(comp, "file", None)
                or getattr(comp, "url", None)
                or getattr(comp, "path", None)
                or ""
            )
            return "i:" + str(ident)
        if name == "Face":
            return "f:" + str(getattr(comp, "id", "") or "")
        if name in ("Record", "Video", "File"):
            return "m:" + str(
                getattr(comp, "file", None) or getattr(comp, "url", None) or ""
            )
        if name in ("Json", "Share", "Music", "Location", "Contact"):
            data = getattr(comp, "data", None) or getattr(comp, "url", None) or ""
            return "c:" + str(data)
        if name == "Poke":
            return "p:" + str(getattr(comp, "id", "") or getattr(comp, "qq", "") or "")
        if name in ("Forward", "Node", "Nodes"):
            return "fw:" + str(getattr(comp, "id", "") or "")
        try:
            payload = comp.toDict() if hasattr(comp, "toDict") else {}
            return "o:" + json.dumps(payload, ensure_ascii=False, sort_keys=True)
        except Exception:  # noqa: BLE001
            return "o:" + str(comp)

    def _message_key(self, event: AstrMessageEvent) -> str:
        """把一条消息压成可比较的签名；空签名表示不作为刷屏内容统计。"""
        if not bool(self.config.get("same_message_only", True)):
            return ANY_KEY
        sigs = []
        for comp in event.get_messages() or []:
            sig = self._component_sig(comp)
            if sig:
                sigs.append(sig)
        return "|".join(sigs)

    # ------------------------------------------------------------------ #
    # 事件：群消息计数
    # ------------------------------------------------------------------ #
    @filter.event_message_type(EventMessageType.GROUP_MESSAGE, priority=100)
    async def on_group_message(self, event: AstrMessageEvent):
        if not bool(self.config.get("enabled", True)):
            return
        self._ensure_cleanup()

        group_id = str(event.get_group_id() or "")
        user_id = str(event.get_sender_id() or "")
        if not group_id or not user_id:
            return
        if user_id == str(event.get_self_id() or ""):
            return
        if bool(self.config.get("exempt_admins", True)) and event.is_admin():
            return
        if user_id in _as_list(self.config.get("whitelist")):
            return

        # notice 类事件（撤回/管理变更/入群等）也会是 GROUP_MESSAGE；
        # only_chat_messages=true 时只统计真正的聊天消息。
        if bool(self.config.get("only_chat_messages", True)):
            raw = getattr(getattr(event, "message_obj", None), "raw_message", None)
            if isinstance(raw, dict) and raw.get("post_type") not in (None, "message"):
                return

        key = self._message_key(event)
        if not key:
            return

        cfg = await self._effective_cfg(group_id)
        now = time.monotonic()
        cooldown_key = (group_id, user_id)
        if now < self._cooldown.get(cooldown_key, 0.0):
            return

        bucket = self._hits[group_id][user_id]
        dq = bucket.get(key)
        if dq is None:
            dq = deque()
            bucket[key] = dq
        dq.append(now)

        cutoff = now - cfg["window_seconds"]
        while dq and dq[0] < cutoff:
            dq.popleft()

        count = len(dq)
        if count < cfg["max_messages"]:
            return

        bucket.clear()  # 触发后清空该用户本轮全部签名，避免二次误伤
        self._cooldown[cooldown_key] = now + cfg["cooldown_seconds"]

        muted = await self._mute(event, group_id, user_id, cfg["mute_seconds"])
        logger.info(
            "[flood_guard] 群 %s 用户 %s 在 %ss 内重复同一条消息 %s 次，禁言 %ss -> %s",
            group_id,
            user_id,
            cfg["window_seconds"],
            count,
            cfg["mute_seconds"],
            "成功" if muted else "失败",
        )

        if not bool(self.config.get("notify", True)):
            return
        chain = self._build_notice(event, cfg, group_id, user_id, count, muted)
        if chain:
            yield event.chain_result(chain)

    # ------------------------------------------------------------------ #
    # 禁言
    # ------------------------------------------------------------------ #
    async def _mute(
        self, event: AstrMessageEvent, group_id: str, user_id: str, seconds: int
    ) -> bool:
        try:
            if event.get_platform_name() == "aiocqhttp":
                from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (  # noqa: E501
                    AiocqhttpMessageEvent,
                )

                if isinstance(event, AiocqhttpMessageEvent):
                    await event.bot.call_action(
                        "set_group_ban",
                        group_id=int(group_id),
                        user_id=int(user_id),
                        duration=int(seconds),
                    )
                    return True
            logger.warning(
                "[flood_guard] 平台 %s 暂不支持自动禁言", event.get_platform_name()
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("[flood_guard] 禁言失败: %s", exc)
        return False

    # ------------------------------------------------------------------ #
    # 播报文案
    # ------------------------------------------------------------------ #
    def _build_notice(
        self,
        event: AstrMessageEvent,
        cfg: dict,
        group_id: str,
        user_id: str,
        count: int,
        muted: bool,
    ) -> list:
        template = str(cfg.get("notify_template") or DEFAULT_TEMPLATE)
        nickname = str(event.get_sender_name() or user_id)
        mapping = {
            "user": nickname,
            "user_id": user_id,
            "nickname": nickname,
            "group_id": group_id,
            "count": str(count),
            "window": str(cfg["window_seconds"]),
            "mute": str(cfg["mute_seconds"]),
            "mute_text": human_duration(cfg["mute_seconds"]) if muted else "（禁言失败）",
        }
        use_at = "{at}" in template
        text = template.replace("{at}", "")
        for key, value in mapping.items():
            text = text.replace("{" + key + "}", value)
        text = text.strip()

        chain: list = []
        if use_at:
            chain.append(Comp.At(qq=user_id))
        if text:
            chain.append(Comp.Plain(text))
        return chain

    @staticmethod
    def _extract_remainder(event: AstrMessageEvent, keyword: str) -> str:
        parts = (event.message_str or "").strip().split()
        for idx, token in enumerate(parts):
            if token == keyword:
                return " ".join(parts[idx + 1:]).strip()
        return ""

    # ------------------------------------------------------------------ #
    # 指令
    # ------------------------------------------------------------------ #
    @filter.command_group("刷屏")
    def flood_group(self):
        """刷屏守卫指令组。"""

    @flood_group.command("帮助")
    async def cmd_help(self, event: AstrMessageEvent):
        yield event.plain_result(
            "刷屏守卫用法（管理员）：\n"
            "/刷屏 状态 —— 查看本群生效配置\n"
            "/刷屏 阈值 <条数> —— 同一条消息重复多少条触发禁言\n"
            "/刷屏 窗口 <秒> —— 统计窗口长度\n"
            "/刷屏 禁言 <秒> —— 禁言时长\n"
            "/刷屏 提示 <文案> —— 自定义本群播报文案\n"
            "/刷屏 重置 —— 清除本群覆盖，回退全局默认\n"
            "占位符：{at} {user} {user_id} {nickname} {group_id} "
            "{count} {window} {mute} {mute_text}"
        )

    @flood_group.command("状态")
    async def cmd_status(self, event: AstrMessageEvent):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield event.plain_result("该指令仅在群聊中可用。")
            return
        cfg = await self._effective_cfg(group_id)
        override = await self.get_kv_data(KV_PREFIX + group_id, None) or {}
        same_only = bool(self.config.get("same_message_only", True))
        only_chat = bool(self.config.get("only_chat_messages", True))
        lines = [
            f"本群（{group_id}）刷屏守卫：",
            f"模式：{'同一条消息重复触发' if same_only else '任意消息条数触发'}",
            f"统计范围：{'仅聊天消息' if only_chat else '包含撤回/管理变更等事件'}",
            f"窗口：{cfg['window_seconds']} 秒",
            f"阈值：{cfg['max_messages']} 条（达到即禁言）",
            f"禁言：{human_duration(cfg['mute_seconds'])}",
            f"播报：{cfg['notify_template']}",
            "覆盖项：" + ("、".join(override.keys()) if override else "无（使用全局默认）"),
        ]
        yield event.plain_result("\n".join(lines))

    @flood_group.command("阈值")
    @filter.permission_type(PermissionType.ADMIN)
    async def cmd_set_max(self, event: AstrMessageEvent, n: int):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield event.plain_result("该指令仅在群聊中可用。")
            return
        if n < 1:
            yield event.plain_result("阈值至少为 1。")
            return
        await self._update_group(group_id, "max_messages", int(n))
        yield event.plain_result(f"✅ 本群阈值已设为 {n} 条（同一条消息重复）。")

    @flood_group.command("窗口")
    @filter.permission_type(PermissionType.ADMIN)
    async def cmd_set_window(self, event: AstrMessageEvent, seconds: int):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield event.plain_result("该指令仅在群聊中可用。")
            return
        if seconds < 1:
            yield event.plain_result("窗口至少为 1 秒。")
            return
        await self._update_group(group_id, "window_seconds", int(seconds))
        yield event.plain_result(f"✅ 本群统计窗口已设为 {seconds} 秒。")

    @flood_group.command("禁言")
    @filter.permission_type(PermissionType.ADMIN)
    async def cmd_set_mute(self, event: AstrMessageEvent, seconds: int):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield event.plain_result("该指令仅在群聊中可用。")
            return
        if seconds < 0:
            yield event.plain_result("禁言时长不能为负。")
            return
        await self._update_group(group_id, "mute_seconds", int(seconds))
        yield event.plain_result(f"✅ 本群禁言时长已设为 {human_duration(seconds)}。")

    @flood_group.command("提示")
    @filter.permission_type(PermissionType.ADMIN)
    async def cmd_set_template(self, event: AstrMessageEvent, text: GreedyStr):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield event.plain_result("该指令仅在群聊中可用。")
            return
        template = (self._extract_remainder(event, "提示") or str(text)).strip()
        if not template:
            yield event.plain_result(
                "用法：/刷屏 提示 {at} 别复读了，禁言 {mute_text}"
            )
            return
        await self._update_group(group_id, "notify_template", template)
        yield event.plain_result(f"✅ 本群播报文案已更新：\n{template}")

    @flood_group.command("重置")
    @filter.permission_type(PermissionType.ADMIN)
    async def cmd_reset(self, event: AstrMessageEvent):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield event.plain_result("该指令仅在群聊中可用。")
            return
        await self.delete_kv_data(KV_PREFIX + group_id)
        yield event.plain_result("✅ 已清除本群覆盖，恢复全局默认。")

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    async def _cleanup_loop(self):
        try:
            while True:
                await asyncio.sleep(300)
                now = time.monotonic()
                for group_id in list(self._hits.keys()):
                    users = self._hits[group_id]
                    for user_id in list(users.keys()):
                        bucket = users[user_id]
                        for key in list(bucket.keys()):
                            dq = bucket[key]
                            while dq and now - dq[0] > 3600:
                                dq.popleft()
                            if not dq:
                                bucket.pop(key, None)
                        if not bucket:
                            users.pop(user_id, None)
                    if not users:
                        self._hits.pop(group_id, None)
                for key in list(self._cooldown.keys()):
                    if now > self._cooldown[key]:
                        self._cooldown.pop(key, None)
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.error("[flood_guard] 清理任务异常: %s", exc)

    async def terminate(self):
        if self._cleanup_task:
            self._cleanup_task.cancel()
