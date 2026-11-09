# -*- coding: utf-8 -*-
"""回归测试：专辑（系列）模式 + 抽象创意参谋。

专辑：create_album / new_pack_in_album / list_albums 的目录与元数据流转；
创意：_extract_json_array 容错、ai_ideas 清洗（打回重写词/去重/截断/丢非字典）；
GUI：专辑管理器新建专辑→新建套→自动载入主窗口→角色图系列复制；创意对话框勾选回填。
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

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QInputDialog, QMessageBox, QTableWidgetItem,
)
from PIL import Image as PImage  # noqa: E402

QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.critical = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)

import core  # noqa: E402
from main import MainWindow, AlbumDialog, IdeasDialog, _pack_status_text  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="album_"))
cfg = {**core.DEFAULT_CONFIG, "packs_dir": str(tmp),
       "api_key": "test-key", "base_url": "http://mock", "text_model": "mock-chat"}

# ---------- core：专辑 ----------
a = core.create_album(cfg, "战斗喵系列", style="pixel art style", desc="测试")
assert (a / "album.json").exists()
assert a.name == "战斗喵系列" and a.parent == tmp
try:
    core.create_album(cfg, "战斗喵系列")
    raise AssertionError("重复建专辑应报 FileExistsError")
except FileExistsError:
    pass
try:
    core.create_album(cfg, "坏/名字")
    raise AssertionError("非法字符应报 ValueError")
except ValueError:
    pass

p1, c1 = core.new_pack_in_album(cfg, a, "日常篇")
assert c1 is False and (p1 / "pack.json").exists()
assert core.load_pack_json(p1)["style"] == "pixel art style", "风格应继承专辑 meta"

buf = io.BytesIO()
PImage.new("RGB", (64, 64), (9, 9, 9)).save(buf, format="PNG")
(p1 / "character.png").write_bytes(buf.getvalue())

p2, c2 = core.new_pack_in_album(cfg, a, "职场篇", from_pack=p1)
assert c2 is True and (p2 / "character.png").exists(), "应复制系列角色图"

albums = core.list_albums(cfg)
assert len(albums) == 1 and albums[0]["meta"]["name"] == "战斗喵系列"
assert [m["name"] for m in albums[0]["packs"]] == ["日常篇", "职场篇"]
assert "角色✓" in _pack_status_text(p2) and "未合成" in _pack_status_text(p2)
print("PASS 1 core 专辑：建专辑/开套/角色图系列复制/列表与状态")

# ---------- core：抽象创意 ----------
fenced = '好的，这是创意：\n```json\n[{"word": "摸鱼", "scene": "上班偷闲", "why": "共鸣"},' \
         ' {"word": "摸、鱼！", "scene": "重复词", "why": "x"},' \
         ' {"word": "摸鱼", "scene": "重复", "why": "x"},' \
         ' {"word": "这不是字典不是字典", "scene": "超长截断", "why": "x"},' \
         ' "不是字典的字符串", {"word": "无语", "scene": "s", "why": "w"},' \
         ' {"word": "开摆", "scene": "摆烂时刻", "why": "玩梗空间大"}]\n```\n'
orig_chat = core._chat
core._chat = lambda *a, **k: fenced
try:
    ideas = core.ai_ideas(cfg, topic="职场")
    words = [i["word"] for i in ideas]
    assert words[0] == "摸鱼"
    assert len(words) == len(set(words)), "词应去重"
    assert all(len(w) <= 4 and "，" not in w and "！" not in w for w in words), "应清洗标点并截到 4 字"
    assert all(isinstance(i, dict) for i in ideas), "非字典项应被丢弃"
    core._chat = lambda *a, **k: "[{\"word\": \"仅一条\"}]"
    try:
        core.ai_ideas(cfg)
        raise AssertionError("创意过少应报错")
    except ValueError:
        pass
finally:
    core._chat = orig_chat
cfg_nok = {**cfg, "text_model": ""}
try:
    core.ai_ideas(cfg_nok)
    raise AssertionError("模型未配全应报 ValueError")
except ValueError:
    pass
print("PASS 2 core 创意参谋：JSON 容错/清洗/去重/截断/配全校验")

# ---------- GUI：专辑管理器 ----------
app = QApplication([])
core.save_config = lambda c: None  # 测试不得改用户真实 config.json
w = MainWindow()
real_cfg = w.cfg
w.cfg = {**core.DEFAULT_CONFIG, "packs_dir": str(tmp)}

answers = iter([("战斗喵系列", True), ("日常篇", True), ("职场篇", True)])
QInputDialog.getText = staticmethod(lambda *a_, **k_: next(answers))

dlg = AlbumDialog(w)
assert dlg.lst_albums.count() == 1 and dlg.lst_packs.count() == 2, "应列出已有专辑和成员"
answers = iter([("节日篇", True)])
QInputDialog.getText = staticmethod(lambda *a_, **k_: next(answers))
dlg._new_pack()  # 新建「节日篇」，复制职场篇角色图
new_dir = tmp / "战斗喵系列" / "节日篇"
assert w.pack_dir == new_dir, f"新建套应自动载入主窗口：{w.pack_dir}"
assert (new_dir / "character.png").exists(), "应复制系列最新角色图"
assert core.load_pack_json(new_dir)["style"] == "pixel art style"
print("PASS 3 GUI 专辑管理器：新建套→自动载入主窗口→角色图系列复制")

# ---------- GUI：创意对话框勾选回填 ----------
d2 = IdeasDialog(w)
d2.tbl.setRowCount(3)
for r, word in enumerate(["已读不回", "在吗", "开摆"]):
    d2.tbl.setItem(r, 0, QTableWidgetItem())
    d2.tbl.setItem(r, 1, QTableWidgetItem(word))
    d2.tbl.item(r, 0).setCheckState(Qt.Checked if r in (0, 2) else Qt.Unchecked)
d2.ed_topic.setText("职场摸鱼")
d2._fill()
hint = w.ed_hint.text()
assert "职场摸鱼" in hint and "已读不回" in hint and "开摆" in hint and "在吗" not in hint
w.cfg = real_cfg
print("PASS 4 GUI 创意参谋：勾选词+主题方向 回填灵感提示")

shutil.rmtree(tmp, ignore_errors=True)
print("ALBUM+IDEAS PASS")
