from __future__ import annotations

from typing import Any


class RoleMapper:
    """角色识别（宽容模式）。

    - 已知客服账号（roles.yaml agents）→ agent，显示中文名
    - 任一 `agent_prefixes` 前缀开头 → agent，显示名 = 去掉前缀（覆盖其他店铺的新客服）
    - 机器人账号（bots）→ bot
    - 其余 → 默认角色（customer），不报错、不纠结
    """

    def __init__(self, roles_config: dict[str, Any]):
        self.agents: dict[str, str] = dict(roles_config.get("agents", {}))
        self.bots: set[str] = set(roles_config.get("bots", []))
        self.bot_prefixes: list[str] = [str(p) for p in (roles_config.get("bot_prefixes") or []) if p]
        self.bot_prefixes: list[str] = [str(p) for p in (roles_config.get("bot_prefixes") or []) if p]
        self.default_role: str = str(roles_config.get("default_role", "customer"))
        # 兼容旧配置单数 agent_prefix，也支持新的 agent_prefixes 列表
        prefixes = roles_config.get("agent_prefixes")
        if not prefixes:
            single = roles_config.get("agent_prefix")
            prefixes = [single] if single else []
        self.agent_prefixes: list[str] = [str(p) for p in prefixes if p]

    def _match_bot_prefix(self, sender_id: str) -> str | None:
        low = sender_id.lower()
        for p in self.bot_prefixes:
            if low.startswith(p.lower()):
                return p
        return None

    def _match_prefix(self, sender_id: str) -> str | None:
        low = sender_id.lower()
        for p in self.agent_prefixes:
            if low.startswith(p.lower()):
                return p
        return None

    def role_for(self, sender_id: str) -> str:
        if sender_id in self.agents:
            return "agent"
        if sender_id in self.bots or self._match_bot_prefix(sender_id):
            return "bot"
        if self._match_prefix(sender_id):
            return "agent"
        # 说明：不能用“名字可读”推断客服——电商平台客户昵称常常也是可读中文（云水川、日粉…）。
        # 未登记账号一律按 default_role（客户）处理；本批次真实的客服从 Excel「客服」列校准。
        return self.default_role

    def display_name(self, sender_id: str) -> str:
        """客服显示中文名；未知的前缀客服去掉前缀；其余原样。"""
        if sender_id in self.agents:
            return str(self.agents[sender_id])
        p = self._match_prefix(sender_id)
        if p:
            return sender_id[len(p):].lstrip("-")
        return sender_id

    def is_known(self, sender_id: str) -> bool:
        return sender_id in self.agents or sender_id in self.bots
