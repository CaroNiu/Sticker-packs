# -*- coding: utf-8 -*-
"""打包成独立可分发应用（当前系统是什么平台就打什么包）。

用法（本机执行，Mac/Linux 同一份脚本）：
    pip install PySide6 Pillow pyinstaller   # 首次
    python build_exe.py

产物：
- Windows: dist/表情包工坊.exe          —— 单文件，发过去双击即用
- macOS:   dist/表情包工坊.app → 表情包工坊-mac.zip —— 解压后拖进「应用程序」；
  首次打开需右键 → 打开（未签名，绕过 Gatekeeper）；数据放
  ~/Library/Application Support/StickerWorkshop/

- skill 的 sticker.py 已内置（vendor/），目标机器无需安装 ray-sticker-shop
- skill 更新后重新跑一次 build_exe.py 即可同步内置副本
- GitHub Actions 云端打包见 .github/workflows/build-mac.yml（Windows 机器也能出 Mac 包）
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
VENDOR = ROOT / "vendor"
SKILL = Path.home() / ".claude" / "skills" / "ray-sticker-shop" / "scripts" / "sticker.py"
IS_MAC = sys.platform == "darwin"
# Windows runner/部分终端 stdout 是 charmap 编码，print 中文/✓ 会 UnicodeEncodeError
if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
# --add-data 的分隔符：Windows 是 ';'，macOS/Linux 是 ':'
SEP = ";" if os.name == "nt" else ":"


def main():
    if not SKILL.exists():
        sys.exit(f"找不到 skill：{SKILL}\n"
                 "先 git clone https://github.com/imraywang/ray-sticker-shop "
                 "~/.claude/skills/ray-sticker-shop 再打包。")
    VENDOR.mkdir(exist_ok=True)
    shutil.copy2(SKILL, VENDOR / "sticker.py")
    print("✓ 已复制 skill 副本 → vendor/sticker.py（随应用内置分发）")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--windowed",
        "--name", "表情包工坊",
        "--add-data", f"{VENDOR / 'sticker.py'}{SEP}vendor",
    ]
    if not IS_MAC:
        cmd.append("--onefile")  # Windows 单文件 exe；Mac 用 .app bundle（onefile 在 mac 双击体验差）
    cmd.append(str(ROOT / "main.py"))
    print(">>", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)

    if IS_MAC:
        app = ROOT / "dist" / "表情包工坊.app"
        if not app.exists():
            sys.exit("打包失败：dist/表情包工坊.app 不存在，看上方 PyInstaller 报错。")
        out = ROOT / "dist" / "表情包工坊-mac.zip"
        if out.exists():
            out.unlink()
        # zip -y 保留符号链接与可执行权限（Python zipfile 不存权限位，解压后 app 打不开）
        subprocess.run(["zip", "-qry", str(out), app.name], check=True, cwd=ROOT / "dist")
        print(f"\n✓ 完成：{out}")
        print("分发：把这个 zip 发给对方。对方：解压 → 拖进「应用程序」→ 右键「打开」一次（未签名）")
    else:
        out = ROOT / "dist" / "表情包工坊.exe"
        if not out.exists():
            sys.exit("打包失败：dist/表情包工坊.exe 不存在，看上方 PyInstaller 报错。")
        print(f"\n✓ 完成：{out}（约 {out.stat().st_size // 1048576} MB）")
        print("分发：直接把这个 exe 发给对方即可。对方首次运行：")
        print("  1) 在 exe 旁边生成 config.json → 设置里填 API Key/地址/模型")
        print("  2) packs/ 自动创建，作品都在里面")


if __name__ == "__main__":
    main()
