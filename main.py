"""astrbot_plugin_flood_guard — repeat-message flood guard with auto-mute.

Detection:
- Default "repeater mode": the SAME message repeated >= threshold within a window triggers.
- Set same_message_only=false to fall back to "any N messages within the window".

Config sources: the plugin config page (_conf_schema.json) + per-group overrides (KV).

Command entry point is a SINGLE flat command to stay robust across AstrBot versions:

    /flood [help|status|limit N|window S|mute S|notice TEXT|reset]

Note: in group chats the bot must be woken first — either use the wake prefix
(default "/") or @ the bot.
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
from astrbot.api.event.filter import EventMessageType
from astrbot.api.star import Context, Star, register

try:  # GreedyStr captures the whole remaining text of a command
    from astrbot.core.star.filter.command import GreedyStr
except Exception:  # pragma: no cover - older versions fall back to plain str
    class GreedyStr(str):
        """Fallback marker; _flood_tokens() recovers the text from message_str."""


PLUGIN_ID = "astrbot_plugin_flood_guard"
KV_PREFIX = "group_cfg:"
ANY_KEY = "__any__"
DEFAULT_TEMPLATE = (
    "{at} 你在 {window} 秒内发送了 {count} 条相同消息，达到上限，已被禁言 {mute_text}。"
)

# keys a group may override
OVERRIDE_KEYS = ("window_seconds", "max_messages", "mute_seconds", "notify_template")
# context segments ignored when building the "same message" signature
IGNORED_SEGMENTS = {"Reply"}

ACTIONS = {
    "help": "help", "?": "help",
    "status": "status", "info": "status",
    "limit": "limit", "max": "limit",
    "window": "window",
    "mute": "mute",
    "notice": "notice", "template": "notice",
    "reset": "reset", "clear": "reset",
}
MEMBER_ACTIONS = {"help", "status"}


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
        return "0s"
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
    return " ".join(parts) or f"{seconds} 秒"


@register(
    PLUGIN_ID,
    "MeowAndy",
    "Flood guard: mute users who repeat the same message; global + per-group limits, custom notice",
    "v0.4.2",
)
class FloodGuardPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        # group_id -> user_id -> { message signature: deque[monotonic ts] }
        self._hits: dict[str, dict[str, dict[str, deque]]] = defaultdict(
            lambda: defaultdict(dict)
        )
        # (group_id, user_id) -> cooldown deadline
        self._cooldown: dict[tuple[str, str], float] = {}
        self._cleanup_task: asyncio.Task | None = None
        self._ensure_cleanup()

    def _ensure_cleanup(self) -> None:
        """Start the background cleanup task lazily so a loop always exists."""
        if self._cleanup_task and not self._cleanup_task.done():
            return
        try:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        except RuntimeError:
            self._cleanup_task = None

    # ------------------------------------------------------------------ #
    # Config
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
    # Permissions
    # AstrBot's PermissionType.ADMIN only matches global admins_id, and
    # sub-command event_filters are skipped during waking, so we check here.
    # ------------------------------------------------------------------ #
    @staticmethod
    def _sender_group_role(event: AstrMessageEvent) -> str:
        """Read the real group role reported by the platform: owner/admin/member."""
        raw = getattr(getattr(event, "message_obj", None), "raw_message", None)
        sender = None
        if hasattr(raw, "get"):
            try:
                sender = raw.get("sender")
            except Exception:  # noqa: BLE001
                sender = None
        if sender is None:
            sender = getattr(raw, "sender", None)
        if isinstance(sender, dict):
            role = str(sender.get("role", "") or "").lower()
            if role:
                return role
        return str(getattr(event, "role", "") or "").lower()

    def _is_group_staff(self, event: AstrMessageEvent) -> bool:
        return self._sender_group_role(event) in ("owner", "admin")

    def _is_astrbot_admin(self, event: AstrMessageEvent) -> bool:
        uid = str(event.get_sender_id() or "")
        admins = []
        try:
            cfg = self.context.get_config()
            admins = cfg.get("admins_id", []) if hasattr(cfg, "get") else []
        except Exception:  # noqa: BLE001
            admins = []
        return uid in {str(x) for x in (admins or [])}

    def _can_manage(self, event: AstrMessageEvent) -> bool:
        uid = str(event.get_sender_id() or "")
        if uid and uid in _as_list(self.config.get("manage_users")):
            return True
        policy = str(self.config.get("manage_permission", "both") or "both").lower()
        if policy == "everyone":
            return True
        if policy == "astrbot_admin":
            return self._is_astrbot_admin(event)
        if policy == "group_admin":
            return self._is_group_staff(event)
        return self._is_group_staff(event) or self._is_astrbot_admin(event)

    # ------------------------------------------------------------------ #
    # Same-message signature
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
        if not bool(self.config.get("same_message_only", True)):
            return ANY_KEY
        sigs = []
        for comp in event.get_messages() or []:
            sig = self._component_sig(comp)
            if sig:
                sigs.append(sig)
        return "|".join(sigs)

    # ------------------------------------------------------------------ #
    # Event: count group messages
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
        if bool(self.config.get("exempt_admins", True)) and self._is_astrbot_admin(event):
            return
        if bool(self.config.get("exempt_group_admins", True)) and self._is_group_staff(event):
            return
        if user_id in _as_list(self.config.get("whitelist")):
            return

        # notice events (recall/admin changes/joins) are GROUP_MESSAGE too
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

        bucket.clear()
        self._cooldown[cooldown_key] = now + cfg["cooldown_seconds"]

        muted = await self._mute(event, group_id, user_id, cfg["mute_seconds"])
        logger.info(
            "[flood_guard] group=%s user=%s repeated same message %s times in %ss, mute %ss -> %s",
            group_id,
            user_id,
            count,
            cfg["window_seconds"],
            cfg["mute_seconds"],
            "ok" if muted else "failed",
        )

        if not bool(self.config.get("notify", True)):
            return
        chain = self._build_notice(event, cfg, group_id, user_id, count, muted)
        if chain:
            yield event.chain_result(chain)

    # ------------------------------------------------------------------ #
    # Mute
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
                "[flood_guard] platform %s does not support auto-mute yet",
                event.get_platform_name(),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("[flood_guard] mute failed: %s", exc)
        return False

    # ------------------------------------------------------------------ #
    # Notice
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

    # ------------------------------------------------------------------ #
    # Single flat command: /flood ...
    # ------------------------------------------------------------------ #
    @filter.command("flood")
    async def cmd_flood(self, event: AstrMessageEvent, args: GreedyStr):
        tokens = self._flood_tokens(event, str(args))
        action_token = tokens[0] if tokens else "status"
        action = ACTIONS.get(action_token.lower(), None)
        params = tokens[1:]

        if action is None:
            yield event.plain_result(self._help_text())
            return

        if action in MEMBER_ACTIONS:
            if action == "help":
                yield event.plain_result(self._help_text())
            else:
                yield event.plain_result(await self._status_text(event))
            return

        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield event.plain_result("该指令仅在群聊中可用。")
            return
        if not self._can_manage(event):
            yield event.plain_result(
                "❌ 没有权限修改本群设置（需要群主/群管理员或机器人管理员）。"
            )
            return

        if action == "reset":
            await self.delete_kv_data(KV_PREFIX + group_id)
            yield event.plain_result("✅ 已清除本群覆盖，回退全局默认。")
            return

        if action == "notice":
            template = " ".join(params).strip()
            if not template:
                yield event.plain_result(
                    "用法：/flood notice {at} 别复读了，禁言 {mute_text}"
                )
                return
            await self._update_group(group_id, "notify_template", template)
            yield event.plain_result("✅ 本群播报文案已更新：\n" + template)
            return

        if not params or not params[0].lstrip("-").isdigit():
            yield event.plain_result(
                f"用法：/flood {action} <数字>"
            )
            return
        value = int(params[0])
        if action == "limit":
            if value < 1:
                yield event.plain_result("阈值至少为 1。")
                return
            await self._update_group(group_id, "max_messages", value)
            yield event.plain_result(f"✅ 本群阈值已设为 {value} 条（同一条消息重复）。")
        elif action == "window":
            if value < 1:
                yield event.plain_result("窗口至少为 1 秒。")
                return
            await self._update_group(group_id, "window_seconds", value)
            yield event.plain_result(f"✅ 本群统计窗口已设为 {value} 秒。")
        elif action == "mute":
            if value < 0:
                yield event.plain_result("禁言时长不能为负数。")
                return
            await self._update_group(group_id, "mute_seconds", value)
            yield event.plain_result(f"✅ 本群禁言时长已设为 {human_duration(value)}。")

    @staticmethod
    def _flood_tokens(event: AstrMessageEvent, args_text: str) -> list[str]:
        """Split the command tail into tokens, tolerating wake prefix/aliases."""
        names = ("flood",)
        text = (args_text or "").strip()
        if not text:
            parts = (event.message_str or "").strip().split()
            cleaned = [p.lstrip("/／!！.") for p in parts]
            if cleaned and cleaned[0].lower() in names:
                parts = parts[1:]
            text = " ".join(parts).strip()
        tokens = text.split()
        if tokens and tokens[0].lstrip("/／!！.").lower() in names:
            tokens = tokens[1:]
        return tokens

    def _help_text(self) -> str:
        return (
            "刷屏守卫 用法（命令为英文）：\n"
            "/flood status | help        查看本群配置 / 帮助\n"
            "/flood limit <数字>         同一条消息重复多少条触发禁言\n"
            "/flood window <秒>          统计窗口\n"
            "/flood mute <秒>            禁言时长\n"
            "/flood notice <文案>        自定义本群播报，如 {at} 别复读了，禁言 {mute_text}\n"
            "/flood reset                清除本群覆盖，回退全局默认\n"
            "占位符：{at} {user} {user_id} {nickname} {group_id} {count} {window} {mute} {mute_text}"
        )

    async def _status_text(self, event: AstrMessageEvent) -> str:
        group_id = str(event.get_group_id() or "")
        if not group_id:
            return "该指令仅在群聊中可用。"
        cfg = await self._effective_cfg(group_id)
        override = await self.get_kv_data(KV_PREFIX + group_id, None) or {}
        same_only = bool(self.config.get("same_message_only", True))
        only_chat = bool(self.config.get("only_chat_messages", True))
        return "\n".join(
            [
                f"刷屏守卫 — 本群 {group_id}",
                "模式：" + ("同一条消息重复触发" if same_only else "任意消息条数触发"),
                "统计范围：" + ("仅聊天消息" if only_chat else "含撤回/管理变更等事件"),
                f"窗口：{cfg['window_seconds']} 秒",
                f"阈值：{cfg['max_messages']} 条（达到即触发）",
                f"禁言：{human_duration(cfg['mute_seconds'])}",
                f"管理权限：{self.config.get('manage_permission', 'both')}",
                f"播报：{cfg['notify_template']}",
                "覆盖项："
                + (", ".join(override.keys()) if override else "无（使用全局默认）"),
            ]
        )

    # ------------------------------------------------------------------ #
    # Lifecycle
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
            logger.error("[flood_guard] cleanup task error: %s", exc)

    async def terminate(self):
        if self._cleanup_task:
            self._cleanup_task.cancel()