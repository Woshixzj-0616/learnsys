"""运行中的对话与写操作确认槽。

这些字典必须全进程一份：包级同名符号只是转发，测试可以直接读写。
"""
from __future__ import annotations

import threading


_ACTIVE: dict[str, threading.Event] = {}
# 一轮运行自己的停止开关：同一会话可以同时有多轮（多标签页 / Web + 快捷栏），
# 停止必须按 run_id 精确命中，不能再靠 conversation_id 覆盖。
_ACTIVE_RUNS: dict[str, threading.Event] = {}
_ACTIVE_LOCK = threading.Lock()

# 写操作确认：key = "run_id:request_id"；等用户点「允许 / 拒绝」或超时。
_CONFIRM: dict[str, dict] = {}
_CONFIRM_LOCK = threading.Lock()
CONFIRM_WAIT_SECONDS = 120

# 唯一落点在 agent/run_record.py；这里保留旧名字给路由包和测试。
from learnsys.agent.run_record import TRACE_KINDS as _TRACE_KINDS
