# -*- coding: utf-8 -*-
"""生成 README 文档截图。

用默认平台（Windows/macOS，有真实字体）渲染，窗口不 show 不抢桌面，
直接 grab() 出图到 docs/screenshots/。与 _render_preview.py（离屏快速
自检）的区别：这里要出「给人看」的图，必须有字体。
"""
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication  # noqa: E402

import main  # noqa: E402
import theme  # noqa: E402

OUT = Path(__file__).parent / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

app = QApplication([])
app.setStyle("Fusion")
theme.apply_theme(app)
app.setWindowIcon(theme.app_icon())

theme._draw_icon(256).save(str(OUT / "icon.png"))

w = main.MainWindow()
w.resize(1150, 860)

def shot(widget, name):
    app.processEvents()
    widget.grab().save(str(OUT / name))
    print("✓", name)

# 窗口未 show，启动时的状态栏临时消息会和项目路径叠印，截图前清掉
w.statusBar().clearMessage()

w.goto_step(0)
shot(w, "step1-character.png")

# 第②步填几行样例文案，表格不显空
w.goto_step(1)
words = ["收到", "好的", "稍等", "哈哈哈", "无语", "谢谢", "抱抱", "加油"]
actions = ["nods twice firmly and gives a big thumbs up, then returns to standing",
           "salutes with one paw, eyes bright, then lowers the paw back down",
           "holds up one finger, glances at an imaginary watch, then looks back up",
           "rolls on the floor laughing with legs kicking in the air, then sits back up",
           "stares blankly with a flat mouth, then slowly turns the head away with a big sigh",
           "bows deeply with both hands together, then pops back up with a big smile",
           "opens both arms wide and squeezes an invisible friend, cheeks glowing",
           "raises both fists in the air cheering with sparkling eyes, then pumps fists again"]
for i, wd in enumerate(words):
    w._add_table_row({"word": wd, "caption": wd, "action": actions[i]})
shot(w, "step2-copywriting.png")

w.goto_step(2)
shot(w, "step3-generate.png")

w.goto_step(3)
shot(w, "step4-delivery.png")

d = main.SettingsDialog(w.cfg, w)
d.resize(680, 620)
shot(d, "settings.png")

print("DOCS RENDER OK →", OUT)
