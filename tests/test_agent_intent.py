# -*- coding: utf-8 -*-
"""排错 / 配置意图识别：表驱动，判据只有 intent.py 一份。"""
from __future__ import annotations

import unittest

from learnsys.agent.intent import detect_ops

NGINX_CONF = """include /etc/nginx/sites-enabled/*;
server{
    listen 80;
    server_name 0.0.0.0;
    root /usr/local/www/tm/public;
    location / { try_files $uri $uri/ /index.php?$args; }
}
server{
    listen 8080;
    server_name 0.0.0.0;
    location / { root /var/www/html; index index.html index.htm; }
}
"""

TRACEBACK = """Traceback (most recent call last):
  File "a.py", line 3, in <module>
    print(1 / 0)
ZeroDivisionError: division by zero
"""

PURE_CODE = """def add(a, b):
    return a + b

print(add(1, 2))
"""

CASES = [
    # (说明, 消息, 期望 ops, 期望 kind)
    ("贴 nginx 配置", NGINX_CONF, True, "config"),
    ("贴 Traceback", TRACEBACK, True, "traceback"),
    ("端口被占用", "8080 端口被占用怎么办？", True, "shell"),
    ("nginx 版本", "nginx 最新版本是多少？", True, "version"),
    ("server_name 合法性", "server_name 写 0.0.0.0 会让 nginx -t 报错吗？",
     True, None),
    ("nginx.conf 改了没变化", "改完 nginx.conf 页面没变化，一般要检查什么？",
     True, "config"),
    ("systemctl 启动失败", "Linux 上 systemctl start 一个服务失败了，怎么查原因？",
     True, "shell"),
    ("要求运行命令", "帮我运行 ls -la /etc/nginx 并把输出贴给我。", True, None),
    ("端口对比追问", "80 和 8080 都是 nginx 的", True, "config"),
    ("默认端口", "FooBar 2027 的默认端口是多少？", True, None),
    ("会话 85 第一问", "为什么我nginx设置两个server一个是80一个是8080，"
     "给的html不一样，但是在本机浏览器看是一个html", True, "config"),
    ("会话 85 追问 2", "有没可能我输入浏览器默认是去8080", True, "config"),
    ("会话 85 追问 3", "但是我改了8080的html他生效了，改80的html没用", True, "config"),
    ("纯概念：三次握手", "什么是 TCP 三次握手？", False, "none"),
    ("纯概念：死锁", "死锁的四个条件是什么？", False, "none"),
    ("空串", "", False, "none"),
    ("纯代码无报错", PURE_CODE, False, "none"),
    ("普通翻译", "把这句话翻译成中文：The quick brown fox.", False, "none"),
    ("网段计算", "一个 /24 网段最多有多少个可用主机地址？怎么算的？", False, "none"),
    ("IP 地址概念", "192.168.1.1 和 10.0.0.1 有什么区别？", False, "none"),
    ("HTTP 状态码概念", "HTTP 404 是什么意思？", False, "none"),
    ("类名含 Server", "class Server:\n    pass\n这段代码报错怎么办", False, "none"),
]


class IntentTableTest(unittest.TestCase):
    def test_table(self):
        for label, message, want_ops, want_kind in CASES:
            with self.subTest(label):
                result = detect_ops(message)
                self.assertEqual(result.ops, want_ops, result)
                if want_kind is not None:
                    self.assertEqual(result.kind, want_kind, result)

    def test_signals_and_confidence(self):
        result = detect_ops(NGINX_CONF)
        self.assertTrue(result.signals)
        self.assertGreaterEqual(result.confidence, 0.5)
        self.assertLessEqual(result.confidence, 1.0)
        self.assertTrue(result.needs_evidence)

    def test_version_needs_evidence(self):
        result = detect_ops("nginx 最新版本是多少？")
        self.assertEqual(result.kind, "version")
        self.assertTrue(result.needs_evidence)

    def test_config_signals_are_readable(self):
        result = detect_ops(NGINX_CONF)
        joined = "、".join(result.signals)
        self.assertTrue(any(word in joined for word in
                            ("listen", "server_name", "server 块", "root")), result)

    def test_context_counts(self):
        result = detect_ops("这是怎么回事", context=NGINX_CONF)
        self.assertTrue(result.ops)
        self.assertEqual(result.kind, "config")

    def test_attachment_counts(self):
        result = detect_ops("帮我看看", attachment_text=TRACEBACK)
        self.assertTrue(result.ops)
        self.assertEqual(result.kind, "traceback")


if __name__ == "__main__":
    unittest.main(verbosity=2)
