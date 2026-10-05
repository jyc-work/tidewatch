"""发布守门：页面数校验 + 原子替换（DESIGN §11.5 / 验收项 #6）。

原则：宁可停更，不可发布半成品或空数据。

⚠️ 部署约束：生产环境用 Docker bind mount 托管 `dist/`。
Docker 挂载的是**目录 inode**，若用 `rename` 替换目录，容器内挂载点会失效（404）。
因此这里采用「**同 inode 内容替换**」：清空 dist 内容 → 拷入新产物。
"""
from __future__ import annotations

import shutil
from pathlib import Path


def count_pages(d: Path) -> int:
    return len(list(d.rglob("*.html"))) if d.exists() else 0


def _clear_contents(d: Path) -> None:
    for item in d.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


def _copy_contents(src: Path, dst: Path) -> None:
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def publish(out_new: Path, out_final: Path, *, min_pages: int = 6) -> tuple[bool, str]:
    """把 out_new 发布为 out_final。页面数不足则拒绝。

    保持 out_final 目录本身（inode 不变），只替换其内容——
    这样 Docker bind mount 不会失效。
    """
    out_new, out_final = Path(out_new), Path(out_final)
    if not out_new.exists():
        return False, f"build dir missing: {out_new}"
    n = count_pages(out_new)
    if n < min_pages:
        return False, f"page count {n} < {min_pages}, refused"

    out_final.mkdir(parents=True, exist_ok=True)
    _clear_contents(out_final)
    _copy_contents(out_new, out_final)
    shutil.rmtree(out_new)
    return True, f"published {n} pages"
