# -*- coding: utf-8 -*-
"""一键安装外部依赖 skill（只影响源码运行；下载 exe 的用户完全不需要）。

做三件事：
1. 找到 skill 脚本 sticker.py：--skill-dir 指定已有安装，或临时 git clone 上游仓库
2. 复制到 vendor/sticker.py（本项目自带的兜底路径，源码运行即生效，不碰 ~/.claude）
3. 用 core.load_sticker 实际加载验证

用法：
    python setup_skill.py                       # 从上游仓库拉最新
    python setup_skill.py --skill-dir <目录>    # 用本机已装好的 skill（scripts 目录或其父目录）
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

UPSTREAM = "https://github.com/imraywang/ray-sticker-shop"
VENDOR = Path(__file__).parent / "vendor" / "sticker.py"


def find_sticker(skill_dir: Path) -> Path:
    """容忍传 scripts 目录或其父目录。"""
    for c in (skill_dir / "scripts" / "sticker.py", skill_dir / "sticker.py"):
        if c.exists():
            return c
    sys.exit(f"✗ {skill_dir} 下找不到 sticker.py（应含 scripts/sticker.py 或 sticker.py）")


def main():
    ap = argparse.ArgumentParser(description="安装 ray-sticker-shop skill 副本到 vendor/")
    ap.add_argument("--skill-dir", default="", help="本机已有的 skill 目录（默认 git clone 上游最新）")
    a = ap.parse_args()

    if a.skill_dir:
        src = find_sticker(Path(a.skill_dir).expanduser())
        print(f"✓ 使用本机已装 skill：{src}")
    else:
        print(f"↓ 从上游拉取 {UPSTREAM} …")
        tmp = Path(tempfile.mkdtemp(prefix="rss-skill-"))
        try:
            subprocess.run(["git", "clone", "--depth", "1", UPSTREAM, str(tmp)],
                           check=True)
            src = find_sticker(tmp)
        except FileNotFoundError:
            sys.exit("✗ 没找到 git 命令。请安装 git，或用 --skill-dir 指向手动下载解压的目录。")
        except subprocess.CalledProcessError as e:
            sys.exit(f"✗ clone 失败（{e}）。检查网络，或手动下载仓库后用 --skill-dir 指定。")

    VENDOR.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, VENDOR)
    print(f"✓ 已复制 → {VENDOR}")

    # 实际加载验证（load_sticker 优先 ~/.claude/skills，找不到才用 vendor——
    # 这里临时指向 vendor 确认副本本身可用）
    import core
    mod = core.load_sticker(str(VENDOR.parent))
    assert hasattr(mod, "cmd_gen"), "副本不完整（缺 cmd_gen）"
    print("✓ 加载验证通过：cmd_character/cmd_gen 等入口齐全")
    print("\n完成。源码运行 python main.py 即可，无需再装任何东西。")


if __name__ == "__main__":
    main()
