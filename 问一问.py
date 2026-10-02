"""打包入口：exe 就是拿这个文件打出来的（源码跑不用它，那个走 问一问.cmd）。

只做一件事 —— 把「问一问」拉起来。
"""
from __future__ import annotations

import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()      # 打包后免得子进程再把整个程序拉一遍
    from learnsys.ask.app import main

    raise SystemExit(main())
