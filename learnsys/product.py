"""产品级命名：只写这一处。

「问一问」仍是一个问答插件/功能名；产品、exe、托盘、窗口、网页品牌统一叫「学习工作台」。
数据目录（D:\\学习系统）、备份文件名、单实例 mutex/管道名是兼容层，**不要**跟着改。
"""
from __future__ import annotations

PRODUCT_NAME = "学习工作台"
QNA_NAME = "问一问"
VERSION = "2.29.0"                      # 版本号只写这一处；界面与打包都从这里取

DESCRIPTION = f"{PRODUCT_NAME} · 框选屏幕问 AI"
EXE_NAME = f"{PRODUCT_NAME}.exe"
LNK_NAME = f"{PRODUCT_NAME}.lnk"
STARTUP_LNK_NAME = f"{PRODUCT_NAME}.lnk"
LAUNCHER_NAME = f"{PRODUCT_NAME}.cmd"      # 源码模式的根目录启动器

# 网页 document.title 的后缀；workbench.py 用同样的值找窗口。
# web/js/shell.js 里有同名常量，tests/test_product.py 会把两边锁死。
WEB_TITLE_SUFFIX = f" · {PRODUCT_NAME}"

# 旧身份只用于迁移清理：原生窗口已退出任务栏，不再需要 AUMID。
LEGACY_AUMID = "Xzj.XueXi.WenYiWen.1"
