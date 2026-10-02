"""只有一个「问一问」—— 再点一次就把它叫回来，不再开第二个。

为什么要有这个："问一问.cmd" 每点一次就是一个新进程（**开机自启 + 手动点**也会叠在一起），
叠出来的第二个会**多一条横栏、多一个托盘图标**，热键还被第一个占着。

两件事：
① **命名互斥体**：进程级的「我在跑」标记 —— 进程一死系统自动清，不留垃圾文件；
② **本地套接字**：第二个进程跟第一个说一声「把横栏露出来」，然后自己退出。
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6 import QtCore, QtNetwork

MUTEX_NAME = "Local\\Xzj.WenYiWen.Single"
PIPE_NAME = "Xzj.WenYiWen.Show"
ERROR_ALREADY_EXISTS = 183
WAIT_MS = 1200

_mutex = None          # 留着别关：一关，后来的进程就以为没人在跑了


def _create_mutex():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    return kernel32, kernel32.CreateMutexW(None, True, MUTEX_NAME)


def claim() -> bool:
    """抢「第一个」的位置。

    True  = 我是第一个，接着往下跑；
    False = 已经有实例在跑（并且已经叫它把横栏露出来了），本进程直接退。
    """
    global _mutex
    try:
        kernel32, handle = _create_mutex()
    except Exception as exc:                    # 互斥体都用不了，就别拦着用户
        print("单实例检查跳过：%s" % exc, file=sys.stderr)
        return True
    if not handle:
        print("单实例检查跳过：CreateMutexW 失败", file=sys.stderr)
        return True
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        ask_to_show()
        return False
    _mutex = handle
    return True


def ask_to_show() -> bool:
    """跟已经在跑的那个说一声「把横栏露出来」（它没应声也不影响我们退）。"""
    socket = QtNetwork.QLocalSocket()
    socket.connectToServer(PIPE_NAME)
    if not socket.waitForConnected(WAIT_MS):
        return False
    socket.write(b"show")
    socket.waitForBytesWritten(WAIT_MS)
    socket.disconnectFromServer()
    return True


class Server(QtCore.QObject):
    """第一个实例守着手边那条本地口子：有人来叫，就把横栏露出来。"""

    called = QtCore.Signal()

    def __init__(self, parent: QtCore.QObject | None = None):
        super().__init__(parent)
        QtNetwork.QLocalServer.removeServer(PIPE_NAME)   # 上次崩了留下的壳，先清掉
        self.server = QtNetwork.QLocalServer(self)
        self.server.newConnection.connect(self._on_connection)
        self.ok = self.server.listen(PIPE_NAME)

    def _on_connection(self) -> None:
        socket = self.server.nextPendingConnection()
        if socket is not None:
            socket.disconnected.connect(socket.deleteLater)
        self.called.emit()

    def close(self) -> None:
        self.server.close()
        QtNetwork.QLocalServer.removeServer(PIPE_NAME)
