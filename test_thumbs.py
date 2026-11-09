# -*- coding: utf-8 -*-
"""回归测试：第③步实时缩略图墙——进页面铺已有图、生成完成实时上墙、重抽原位更新。"""
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402
from PIL import Image as PImage  # noqa: E402

QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.critical = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)

from main import MainWindow  # noqa: E402

app = QApplication([])
w = MainWindow()
assert hasattr(w, "thumb_list"), "thumb_list 未创建"

# 造一个临时项目：3 张精灵图 + 1 张素材
tmp = Path(tempfile.mkdtemp(prefix="thumbs_"))
(tmp / "sheets").mkdir()
(tmp / "assets_raw").mkdir()
buf = io.BytesIO()
PImage.new("RGB", (256, 256), (200, 120, 120)).save(buf, format="PNG")
png = buf.getvalue()
(tmp / "pack.json").write_text(json.dumps(
    {"name": "缩略图测试", "stickers": [{"word": "a"}, {"word": "b"}, {"word": "c"}]},
    ensure_ascii=False), encoding="utf-8")
for n in ("01.png", "02.png", "03.png"):
    (tmp / "sheets" / n).write_bytes(png)
(tmp / "assets_raw" / "cover.png").write_bytes(png)

w.pack_dir = tmp
w.goto_step(2)  # 进第③步应自动铺已有图
assert w.thumb_list.count() == 4, f"进页应铺 4 张，实际 {w.thumb_list.count()}"
print("PASS 1 进第③步自动铺已有图（3 精灵图 + 1 素材）")

# 模拟生成完一张：实时上墙
buf2 = io.BytesIO()
PImage.new("RGB", (2048, 2048), (120, 200, 120)).save(buf2, format="PNG")
(tmp / "sheets" / "04.png").write_bytes(buf2.getvalue())
w._on_gen_progress("04.png", "ok", "完成 sheets/04.png")
assert w.thumb_list.count() == 5, f"生成完应实时上墙，实际 {w.thumb_list.count()}"
assert w.thumb_list.item(4).text() == "04.png"
print("PASS 2 生成完成回调实时上墙（04.png）")

# 模拟重抽同一张：原位更新，不新增
buf3 = io.BytesIO()
PImage.new("RGB", (2048, 2048), (120, 120, 200)).save(buf3, format="PNG")
(tmp / "sheets" / "04.png").write_bytes(buf3.getvalue())
w._on_gen_progress("04.png", "ok", "完成 sheets/04.png")
assert w.thumb_list.count() == 5, f"重抽不应新增条目，实际 {w.thumb_list.count()}"
print("PASS 3 重抽同名图原位更新，不重复")

# 缺文件/坏名不炸
w._on_gen_progress("99.png", "ok", "完成（文件其实没了）")
w._on_gen_progress("", "ok", "空名")
print("PASS 4 缺文件/空名静默忽略不炸")

shutil.rmtree(tmp, ignore_errors=True)
print("THUMBS PASS")
