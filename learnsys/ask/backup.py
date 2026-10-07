"""数据备份：把 D:\学习系统 整包 zip 到旁边，防手滑/防盘坏。

默认每周自动一次（启动时检查），托盘里也能「立即备份」。纯标准库，不带 Qt。
"""
from __future__ import annotations

import datetime
import pathlib
import zipfile

KEEP = 8                    # 留最近几份，多了自动删
AUTO_EVERY_DAYS = 7         # 自动备份间隔
_SKIP_NAMES = {"备份", "backup"}          # 数据目录里不打包的东西
_SKIP_SUFFIX = (".zip", ".tmp")


def _should_skip(path: pathlib.Path, data_root: pathlib.Path) -> bool:
    rel = path.relative_to(data_root)
    if any(part in _SKIP_NAMES for part in rel.parts):
        return True
    return path.suffix.lower() in _SKIP_SUFFIX


def do_backup(data_root: pathlib.Path, backup_dir: pathlib.Path,
              keep: int = KEEP, when: datetime.datetime | None = None) -> pathlib.Path:
    """把 data_root 打成 zip 放进 backup_dir，返回 zip 路径。打完顺手按 keep 清旧的。"""
    data_root = pathlib.Path(data_root)
    backup_dir = pathlib.Path(backup_dir)
    if not data_root.is_dir():
        raise FileNotFoundError(f"数据目录不存在：{data_root}")
    backup_dir.mkdir(parents=True, exist_ok=True)
    when = when or datetime.datetime.now()
    stamp = when.strftime("%Y%m%d_%H%M")
    zip_path = backup_dir / f"学习系统_{stamp}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(data_root.rglob("*")):
            if not path.is_file() or _should_skip(path, data_root):
                continue
            try:
                zf.write(path, path.relative_to(data_root))
            except OSError:
                continue            # 正在写的库/被占用的文件跳过，别让备份整个失败
    prune(backup_dir, keep)
    return zip_path


def prune(backup_dir: pathlib.Path, keep: int = KEEP) -> list[str]:
    """只留最近 keep 份，删掉更老的。返回删掉的文件名。"""
    zips = sorted(pathlib.Path(backup_dir).glob("学习系统_*.zip"))
    removed = []
    for old in zips[:-keep] if keep > 0 else []:
        try:
            old.unlink()
            removed.append(old.name)
        except OSError:
            pass
    return removed


def newest_backup(backup_dir: pathlib.Path) -> pathlib.Path | None:
    zips = sorted(pathlib.Path(backup_dir).glob("学习系统_*.zip"))
    return zips[-1] if zips else None


def needs_backup(backup_dir: pathlib.Path, every_days: int = AUTO_EVERY_DAYS) -> bool:
    """距上一份备份超过 every_days 天（或一份都没有）⇒ 该备了。"""
    newest = newest_backup(backup_dir)
    if newest is None:
        return True
    try:
        age = datetime.datetime.now() - datetime.datetime.fromtimestamp(newest.stat().st_mtime)
    except OSError:
        return True
    return age.total_seconds() > every_days * 86400
