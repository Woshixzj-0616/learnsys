"""学习工作台：框选屏幕一块 → 问 AI → 卡片里出答案（问答部分叫「问一问」）。"""

# 版本号**只写一处**：`learnsys/product.py` 的 VERSION；这里只做兼容再导出。
# 改完记得同步「学习工作台.cmd 会优先启动 dist 里的 exe」——
# 源码比 exe 新时启动会提醒重新打包（见 app.py 的 _exe_is_stale）。
from learnsys.product import VERSION

__all__ = ["VERSION"]
