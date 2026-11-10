# -*- coding: utf-8 -*-
"""回归测试：单张微调——参考图换成该图本身 + 原 prompt 拼微调指令 + 覆盖原图。

微调 vs 重抽的本质区别：参考图必须是「那张已生成的图」（保持画风构图），
而不是 character.png（那是首生成时的参考）。校验 fake _edit 收到的 image_path。
"""
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

import core  # noqa: E402

# --- fixture：tmp 项目，07.png 已生成，09.png 未生成 ---
tmp = Path(tempfile.mkdtemp(prefix="tweak_"))
(tmp / "sheets").mkdir()
buf = io.BytesIO()
PImage.new("RGB", (64, 64), (200, 120, 120)).save(buf, format="PNG")
old_png = buf.getvalue()
(tmp / "pack.json").write_text(json.dumps(
    {"name": "微调测试", "character": "character.png",
     "stickers": [{"word": "你好", "action": "waving hello"},
                  {"word": "再见", "action": "waving goodbye"},
                  {"word": "哈哈", "action": "laughing loudly"},
                  {"word": "无语", "action": "rolling eyes"},
                  {"word": "谢谢", "action": "bowing thanks"},
                  {"word": "好的", "action": "nodding firmly"},
                  {"word": "摸鱼", "action": "slacking at desk"},
                  {"word": "开摆", "action": "lying flat"},
                  {"word": "加油", "action": "raising fists"}]},
    ensure_ascii=False), encoding="utf-8")
(tmp / "character.png").write_bytes(old_png)
(tmp / "sheets" / "07.png").write_bytes(old_png)  # 只有 07 已生成

cfg = {**core.DEFAULT_CONFIG, "api_key": "test-key", "base_url": "http://mock"}
sticker = core.load_sticker(cfg["skill_dir"])

# --- fake _edit：捕获调用参数，返回一张新 PNG ---
calls = []
buf2 = io.BytesIO()
PImage.new("RGB", (64, 64), (120, 200, 120)).save(buf2, format="PNG")
new_png = buf2.getvalue()


def fake_edit(image_path, prompt, size, background, model, quality, log_path):
    calls.append({"image": Path(image_path).resolve(), "prompt": prompt,
                  "size": size, "background": background})
    return new_png


sticker._edit = fake_edit  # 覆盖 dispatch，拦截真实 API

# --- PASS 1: 正常微调——参考图是它自己，prompt 带原 action + 指令，文件被覆盖 ---
r = core.tweak_sheet(sticker, cfg, tmp, "07.png", "嘴巴张更大，表情更夸张")
assert calls, "fake _edit 未被调用"
assert calls[0]["image"] == (tmp / "sheets" / "07.png").resolve(), \
    f"参考图必须是该图本身，实际 {calls[0]['image']}"
assert "slacking at desk" in calls[0]["prompt"], "prompt 应含原 action"
assert "嘴巴张更大" in calls[0]["prompt"], "prompt 应含微调指令"
assert "保持" in calls[0]["prompt"], "prompt 应要求未提及部分保持原样"
assert calls[0]["background"] == "transparent"
assert (tmp / "sheets" / "07.png").read_bytes() == new_png, "原图应被覆盖为新图"
assert r["item"] == "07.png" and r["bytes"] == len(new_png)
print("PASS 1 微调：参考图=自身、prompt 拼接、覆盖原图")

# --- PASS 2: 未生成的图 → 明确报错 ---
try:
    core.tweak_sheet(sticker, cfg, tmp, "09.png", "微调")
    raise AssertionError("未生成的图应报错")
except ValueError as e:
    assert "还没生成" in str(e), str(e)
print("PASS 2 未生成的图：明确报错引导先开始生成")

# --- PASS 3: 无效 item / 空指令 → ValueError ---
try:
    core.tweak_sheet(sticker, cfg, tmp, "99.png", "微调")
    raise AssertionError("无效 item 应报错")
except ValueError:
    pass
try:
    core.tweak_sheet(sticker, cfg, tmp, "07", "  ")
    raise AssertionError("空指令应报错")
except ValueError:
    pass
print("PASS 3 无效 item / 空指令：ValueError")

# --- PASS 4: GUI TweakDialog——快捷指令追加与取词 ---
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402
from main import TweakDialog, MainWindow  # noqa: E402

app = QApplication([])
w = MainWindow()
dlg = TweakDialog(w, "07.png")
assert dlg.instruction() == ""
dlg.ed_inst.setText("背景更简洁")
assert dlg.instruction() == "背景更简洁"
dlg._append("色调更暖")
assert dlg.instruction() == "背景更简洁，色调更暖"
dlg._append("色调更暖")  # 重复追加应忽略
assert dlg.instruction() == "背景更简洁，色调更暖"
dlg._go()
assert dlg.result() == int(QDialog.DialogCode.Accepted), "有指令时 _go 应 accept"
print("PASS 4 TweakDialog：快捷指令追加去重、取词、确认")

shutil.rmtree(tmp, ignore_errors=True)
print("TWEAK PASS")
