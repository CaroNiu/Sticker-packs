# -*- coding: utf-8 -*-
"""回归测试：Worker 被 deleteLater 后残留僵尸引用，导致后续任务全被 _run 守卫炸掉。

线上现象（2026-11-09）：点过一次「预估花费」后再点「开始生成」，界面永远“提交中”、
无任何日志，控制台每秒刷 `libshiboken: Internal C++ object (Worker) already deleted`。
根因：QThread C++ 对象被 deleteLater 回收后，self.worker.isRunning() 抛 RuntimeError，
_run 的忙碌守卫先炸 → 新任务根本没启动；_tick 每秒再炸一次。
"""
import io
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

# 测试里绝不能弹模态框（守卫若误判会卡死测试）
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.critical = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)

import core  # noqa: E402
from main import MainWindow, Worker  # noqa: E402

app = QApplication([])
w = MainWindow()

# 自带临时项目（2 个待生成 sticker）：不依赖用户真实数据——真实项目可能已全部生成完，todo=0
from PIL import Image as PImage  # noqa: E402
tmp = Path(tempfile.mkdtemp(prefix="zombie_"))
(tmp / "pack.json").write_text(json.dumps(
    {"name": "僵尸测试", "character": "character.png",
     "stickers": [{"word": "摸鱼", "action": "slacking off at desk"},
                  {"word": "开摆", "action": "lying flat on floor"}]},
    ensure_ascii=False), encoding="utf-8")
buf = io.BytesIO()
PImage.new("RGB", (8, 8), (9, 9, 9)).save(buf, format="PNG")
(tmp / "character.png").write_bytes(buf.getvalue())
w.pack_dir = tmp

errors = []


def pump_until_worker_gone(max_ms=8000):
    t0 = time.monotonic()
    while time.monotonic() - t0 < max_ms / 1000:
        app.processEvents()
        if w.worker is None:
            for _ in range(30):  # 再泵几圈让 deleteLater 事件落地
                app.processEvents()
            return True
        time.sleep(0.01)
    return False


def run_task(flag):
    w._run("测试中…", core.dry_run, w.sticker, w.cfg, w.pack_dir, True,
           step=2, on_done=lambda r: flag.append(r["count"]),
           on_fail=lambda m: errors.append(m))


# --- PASS 1: 正常一轮任务，结束后 worker 引用应被清干净 ---
first = []
run_task(first)
ok = pump_until_worker_gone()
assert ok, "worker 未在时限内结束并清理"
assert first and first[0] >= 1, f"任务未成功完成：{errors}"
assert w.worker is None, "任务结束后 worker 引用未清（会留僵尸）"
print(f"PASS 1 任务正常完成（dry_run={first[0]} 张），worker 引用已自动清理")

# --- PASS 2: 手工制造僵尸（绕过 _on_worker_gone，模拟老版本残留）---
zomb = Worker(lambda: None)
zomb.finished.connect(zomb.deleteLater)  # 故意不连 _on_worker_gone
zomb.start()
while zomb.isRunning():
    app.processEvents()
    time.sleep(0.01)
for _ in range(50):
    app.processEvents()
w.worker = zomb
try:
    zomb.isRunning()
    raise AssertionError("僵尸未复现：isRunning 没抛 RuntimeError（环境时序变化？）")
except RuntimeError:
    pass
print("PASS 2 僵尸场景已复现：isRunning() 对已删除 C++ 对象抛 RuntimeError")

# --- PASS 3: _worker_alive/_tick 对僵尸免疫，且顺手清掉引用 ---
assert w._worker_alive() is False, "_worker_alive 应返回 False"
assert w.worker is None, "僵尸引用未被清理"
w._tick()  # 老代码这里每秒刷一次 traceback
print("PASS 3 _worker_alive/_tick 对僵尸免疫且已清引用")

# --- PASS 4: 僵尸之后新任务能正常启动（老代码在 _run 守卫处就炸了）---
second = []
run_task(second)
ok = pump_until_worker_gone()
assert ok and second and second[0] >= 1, f"僵尸之后新任务没跑起来：{errors or second}"
print(f"PASS 4 僵尸之后新任务正常启动并完成（dry_run={second[0]} 张）")
shutil.rmtree(tmp, ignore_errors=True)
print("ZOMBIE FIX PASS")
