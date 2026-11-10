# -*- coding: utf-8 -*-
"""渲染预览：离屏实例化主窗口各步骤页 + 设置对话框，截图供人工检查样式。"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication  # noqa: E402

import main  # noqa: E402
import theme  # noqa: E402

out_dir = os.path.dirname(os.path.abspath(__file__))

app = QApplication([])
app.setStyle("Fusion")
theme.apply_theme(app)

w = main.MainWindow()
w.resize(1150, 800)
w.show()
app.processEvents()
w.grab().save(os.path.join(out_dir, "_preview_step1.png"))

w.goto_step(1)
app.processEvents()
w.grab().save(os.path.join(out_dir, "_preview_step2.png"))

w.goto_step(2)
app.processEvents()
w.grab().save(os.path.join(out_dir, "_preview_step3.png"))

w.goto_step(3)
app.processEvents()
w.grab().save(os.path.join(out_dir, "_preview_step4.png"))

d = main.SettingsDialog(w.cfg, w)
d.resize(680, 620)
d.show()
app.processEvents()
d.grab().save(os.path.join(out_dir, "_preview_settings.png"))

print("RENDER OK")
