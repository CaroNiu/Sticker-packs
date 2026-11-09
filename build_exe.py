# -*- coding: utf-8 -*-
"""打包成 Windows 独立单文件 exe（发到其他 PC 双击即用）。

用法（在有 skill 的开发机上）：
    pip install pyinstaller   # 首次
    python build_exe.py

产物：dist/表情包工坊.exe
- 双击运行；首次运行在 exe 旁边生成 config.json（填 API Key/地址/模型）和 packs/（作品目录）
- skill 的 sticker.py 已内置进 exe，目标机器无需安装 ray-sticker-shop
- skill 更新后重新跑一次 build_exe.py 即可同步内置副本
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
VENDOR = ROOT / "vendor"
SKILL = Path.home() / ".claude" / "skills" / "ray-sticker-shop" / "scripts" / "sticker.py"


def main():
    if not SKILL.exists():
        sys.exit(f"找不到 skill：{SKILL}\n"
                 "先 git clone https://github.com/imraywang/ray-sticker-shop 再打包。")
    VENDOR.mkdir(exist_ok=True)
    shutil.copy2(SKILL, VENDOR / "sticker.py")
    print("✓ 已复制 skill 副本 → vendor/sticker.py（随 exe 内置分发）")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--windowed", "--onefile",
        "--name", "表情包工坊",
        "--add-data", f"{VENDOR / 'sticker.py'};vendor",
        str(ROOT / "main.py"),
    ]
    print(">>", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)

    out = ROOT / "dist" / "表情包工坊.exe"
    if out.exists():
        print(f"\n✓ 完成：{out}（约 {out.stat().st_size // 1048576} MB）")
        print("分发：直接把这个 exe 发给对方即可。对方首次运行：")
        print("  1) 在 exe 旁边生成 config.json → 设置里填 API Key/地址/模型")
        print("  2) packs/ 自动创建，作品都在里面")
    else:
        sys.exit("打包失败：dist/表情包工坊.exe 不存在，看上方 PyInstaller 报错。")


if __name__ == "__main__":
    main()
