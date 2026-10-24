"""Qt 侧的 HTTP 客户端：只跟本机后台说话。

口径和 `web/js/api.js` 一致：
- 令牌从公开的 `GET /api/health` 取，只存内存；
- 错误优先用后端 `detail`，403 换成可操作的中文提示；
- 请求在 Qt 主线程异步发出，回调走 Python 函数，不另起线程。
"""
from __future__ import annotations

import json

from PySide6 import QtCore, QtNetwork

TOKEN_HEADER = b"X-Learnsys-Token"
TOKEN_ERROR = "本地令牌不对，关掉窗口重试；还不行就重启学习工作台"


def error_text(status: int, body: bytes | str) -> str:
    """把后端的错误响应翻成一句中文；403 单独给可操作提示。"""
    text = (body.decode("utf-8", "replace")
            if isinstance(body, (bytes, bytearray)) else str(body or ""))
    detail = ""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        data = None
    if isinstance(data, dict) and isinstance(data.get("detail"), str):
        detail = data["detail"]
    if status == 403:
        return TOKEN_ERROR
    return detail or f"请求失败（{status}）"


def connection_text(reason: str = "") -> str:
    """服务没起来 / 中途断开。"""
    tail = f"（{reason}）" if reason else ""
    return f"本地服务没起来或已断开{tail}。点「重试」再连一次"


def _ignore(_message: str) -> None:
    pass


class ApiClient(QtCore.QObject):
    """一个窗口一个客户端；`start()` 拿令牌，之后才发业务请求。"""

    ready = QtCore.Signal()
    failed = QtCore.Signal(str)

    def __init__(self, port: int, parent: QtCore.QObject | None = None):
        super().__init__(parent)
        self.port = int(port)
        self.base = f"http://127.0.0.1:{self.port}"
        self.token = ""
        self.version = ""
        self._manager = QtNetwork.QNetworkAccessManager(self)

    # ---- 连接 ----

    def start(self) -> None:
        """重新拿一次令牌（也用于「重试」）。"""
        self.token = ""
        self._send("GET", "/api/health", None, self._health_ok,
                   lambda message: self.failed.emit(message), auth=False)

    def _health_ok(self, data: dict) -> None:
        token = str((data or {}).get("token") or "")
        if not token:
            self.failed.emit("后台回了奇怪的响应：没有本地令牌")
            return
        self.token = token
        self.version = str(data.get("version") or "")
        self.ready.emit()

    # ---- 业务请求 ----

    def get(self, path: str, on_ok, on_err=None) -> None:
        self._send("GET", path, None, on_ok, on_err or _ignore)

    def post(self, path: str, body: dict | None, on_ok, on_err=None) -> None:
        self._send("POST", path, body or {}, on_ok, on_err or _ignore)

    def delete(self, path: str, on_ok, on_err=None) -> None:
        self._send("DELETE", path, None, on_ok, on_err or _ignore)

    # ---- 收发 ----

    def _send(self, method: str, path: str, body: dict | None,
              on_ok, on_err, auth: bool = True) -> None:
        request = QtNetwork.QNetworkRequest(QtCore.QUrl(self.base + path))
        request.setRawHeader(b"Content-Type", b"application/json")
        if auth and self.token:
            request.setRawHeader(TOKEN_HEADER, self.token.encode("utf-8"))

        if method == "GET":
            reply = self._manager.get(request)
        elif method == "POST":
            payload = json.dumps(body or {}, ensure_ascii=False).encode("utf-8")
            reply = self._manager.post(request, QtCore.QByteArray(payload))
        else:
            reply = self._manager.deleteResource(request)

        # 闭包持有 reply：PySide 的 reply 在 finished 前不能提前回收
        reply.finished.connect(lambda: self._finish(reply, on_ok, on_err))

    def _finish(self, reply: QtNetwork.QNetworkReply, on_ok, on_err) -> None:
        status = reply.attribute(
            QtNetwork.QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        raw = bytes(reply.readAll())
        reason = reply.errorString()
        reply.deleteLater()

        if status is None:
            on_err(connection_text(reason))
            return
        status = int(status)
        if not 200 <= status < 300:
            on_err(error_text(status, raw))
            return
        if not raw:
            on_ok({})
            return
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            on_err("后台返回的不是 JSON；先重试，还不行就重启学习工作台")
            return
        on_ok(data)
