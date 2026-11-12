# -*- coding: utf-8 -*-
"""表情包工坊桌面版（PySide6）。

把 ray-sticker-shop skill 的 5 个命令包成图形界面：
① 定角色 → ② 写文案 → ③ 生成 → ④ 合成/检查/交付。
"""
import sys
import time
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QIcon, QImageReader, QMovie, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
    QPushButton, QProgressBar, QScrollArea, QSpinBox, QStackedWidget, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

import core
import theme
from theme import apply_theme

STYLES = [
    # 默认首位：熊猫头式情绪原型（大头、表情浓度、自带态度的脸）
    "meme-style cartoon, oversized expressive head, tiny simple body, thick clean outlines, flat colors, smug cheeky default face",
    "cute chibi, two-head-tall, thick clean dark outlines, flat soft colors",
    "thick clean dark outlines, flat colors",
    "hand-drawn crayon doodle style, grainy texture",
    "kawaii pastel style, soft round shapes",
    "pixel art style, chunky pixels",
]

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")

STEP_NAMES = ["① 定角色", "② 写文案", "③ 生成", "④ 合成·检查·交付"]

BAD_NAME_CHARS = " \t，。！？、,.!?/\\:\"'*<>|"

# 总览面板各状态的配色（边框/底色/字色/字重），与 theme.py 的调性一致
CHIP_STYLES = {
    "pending": ("#D8D2C7", "#FFFFFF", "#8D877D", "normal"),
    "partial": ("#E3A23C", "#FDF4E3", "#8A6215", "normal"),
    "run":     ("#4A8FD4", "#EAF3FC", "#23639F", "bold"),
    "done":    ("#57A56A", "#EDF7EE", "#2E7A42", "normal"),
    "error":   ("#C43D3D", "#FCEDED", "#C43D3D", "bold"),
}


def _chip_ss(level):
    bd, bg, fg, wt = CHIP_STYLES[level]
    return (f"QPushButton{{border:1px solid {bd};background:{bg};color:{fg};"
            f"border-radius:10px;padding:6px 12px;text-align:left;font-weight:{wt};}}"
            f"QPushButton:checked{{border:2px solid {bd};font-weight:600;}}")


def _fmt_mmss(sec):
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"


def _counter_row(field, lbl):
    """输入框 + 右侧字数计数标签，合成一行（省得计数单独占一行）。"""
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(6)
    h.addWidget(field, 1)
    h.addWidget(lbl)
    return w


# ---------- 后台线程 ----------

class Worker(QThread):
    """通用后台任务线程。

    with_progress=True 时，run() 会把 self.progress.emit 作为最后一个
    位置参数传给 fn（fn 的签名须以 progress 回调结尾）。
    进度一律走信号回 UI 线程，不允许跨线程直接碰控件。
    """
    progress = Signal(object, str, str)   # (item, kind, msg)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, *args, with_progress=False):
        super().__init__()
        self.fn, self.args = fn, args
        self.with_progress = with_progress

    def run(self):
        try:
            if self.with_progress:
                result = self.fn(*self.args, self.progress.emit)
            else:
                result = self.fn(*self.args)
            self.done.emit(result)
        except SystemExit as e:  # sticker.py 用 sys.exit 报业务错误
            self.failed.emit(str(e) or "操作被终止")
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")


# ---------- 拖拽区 ----------

class DropLabel(QLabel):
    pathSelected = Signal(str)

    def __init__(self, parent=None):
        super().__init__("把照片拖到这里\n（或点右侧「浏览」选择）", parent)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(170)
        self.setStyleSheet(
            "QLabel{border: 2px dashed #E0B7A5; border-radius: 12px; color: #8D877D;"
            "font-size: 14px; background: #FDFBF8;}")
        self._photo = None

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if p.lower().endswith(IMAGE_EXTS):
                self.set_photo(p)
                return

    def set_photo(self, p):
        self._photo = p
        pm = QPixmap(p)
        if not pm.isNull():
            self.setPixmap(pm.scaledToHeight(150, Qt.SmoothTransformation))
        else:
            self.setText(f"无法读取图片：\n{p}")
        self.pathSelected.emit(p)

    def photo(self):
        return self._photo


# ---------- 提示词对话框（无 key 模式）----------

class PromptsDialog(QDialog):
    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.setWindowTitle("出图提示词（复制到 ChatGPT / Codex 使用）")
        self.resize(760, 640)
        v = QVBoxLayout(self)
        tip = QLabel("没有 API Key 也能用：复制下面的提示词，到 ChatGPT 里上传角色图出图，"
                     "把结果按括号里的路径存进项目目录，然后回来点「合成」即可。")
        tip.setWordWrap(True)
        v.addWidget(tip)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        iv = QVBoxLayout(inner)
        for path, prompt in items:
            lbl = QLabel(path)
            lbl.setStyleSheet("font-weight: bold;")
            iv.addWidget(lbl)
            box = QPlainTextEdit(prompt)
            box.setReadOnly(True)
            box.setMaximumHeight(110)
            iv.addWidget(box)
            btn = QPushButton("复制这条提示词")
            btn.clicked.connect(lambda _, t=prompt: QApplication.clipboard().setText(t))
            row = QHBoxLayout()
            row.addStretch(1)
            row.addWidget(btn)
            iv.addLayout(row)
        iv.addStretch(1)
        scroll.setWidget(inner)
        v.addWidget(scroll)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)


# ---------- 后台调用日志面板 ----------

class ApiLogPanel(QWidget):
    """HTTP 级调用日志（默认收起，勾选展开实时滚动）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._consumed = 0   # 已展示的历史行数（对齐 core 的全局行号）
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        self.cb = QCheckBox("显示后台调用日志（请求/重试/耗时，排查卡顿用）")
        self.cb.toggled.connect(self._toggle)
        top.addWidget(self.cb)
        top.addStretch(1)
        btn_clear = QPushButton("清空")
        btn_clear.clicked.connect(lambda: self.txt.clear())
        top.addWidget(btn_clear)
        v.addLayout(top)
        self.txt = QPlainTextEdit()
        self.txt.setReadOnly(True)
        self.txt.setMaximumHeight(150)
        self.txt.setObjectName("apiLog")
        self.txt.setPlaceholderText("勾选后实时显示 API 调用细节…")
        self.txt.hide()
        v.addWidget(self.txt)

    def _toggle(self, on):
        if on:
            self._drain_backlog()
        self.txt.setVisible(on)

    def _drain_backlog(self):
        """把折叠期间攒下的日志按全局行号补齐，不重不漏。"""
        back, total = core.get_api_log()
        skip = total - len(back)          # 被 deque 环绕挤掉的头部队
        idx = max(self._consumed - skip, 0)
        if idx < len(back):
            self.txt.appendPlainText("\n".join(back[idx:]))
        self._consumed = total

    def append(self, line):
        if self.cb.isChecked():
            self.txt.appendPlainText(line)
            self._consumed = core.get_api_log()[1]
            sb = self.txt.verticalScrollBar()
            sb.setValue(sb.maximum())


# ---------- 设置对话框 ----------

class SettingsDialog(QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(680, 620)
        self.cfg = dict(cfg)
        root = QVBoxLayout(self)

        # ---- 组 1：图片生成模型 ----
        g1 = QGroupBox("图片生成模型（出角色图 / 精灵图 / 素材 · 任意 OpenAI 兼容服务）")
        form = QFormLayout(g1)

        self.ed_key = QLineEdit(cfg.get("api_key", ""))
        self.ed_key.setEchoMode(QLineEdit.Password)
        self.ed_key.setPlaceholderText("sk-...（留空 = 无 key 手动出图模式）")
        form.addRow("图片 API Key", self.ed_key)

        self.ed_base = QLineEdit(cfg.get("base_url", ""))
        self.ed_base.setPlaceholderText(
            "任意 OpenAI 兼容图片接口（OpenAI 官方留空；火山方舟 …/api/v3 或套餐 …/api/plan）")
        form.addRow("图片接口地址", self.ed_base)

        # 任意 OpenAI 兼容服务都能用：官方 / 火山方舟 / 中转聚合网关 / 本地推理，模型 ID 手填即可
        self.cb_char_model = QComboBox()
        self.cb_char_model.setEditable(True)
        self.cb_char_model.addItems([
            cfg.get("character_model") or "gpt-image-1",
            "gpt-image-1", "doubao-seedream-4-0-250828", "doubao-seededit-3-0-i2i",
        ])
        self.cb_char_model.setCurrentText(cfg.get("character_model") or "gpt-image-1")
        form.addRow("角色图模型", self.cb_char_model)

        self.cb_gen_model = QComboBox()
        self.cb_gen_model.setEditable(True)
        self.cb_gen_model.addItems([
            cfg.get("gen_model") or "gpt-image-1",
            "gpt-image-1", "doubao-seedream-4-0-250828", "doubao-seededit-3-0-i2i",
        ])
        self.cb_gen_model.setCurrentText(cfg.get("gen_model") or "gpt-image-1")
        form.addRow("生成模型", self.cb_gen_model)

        row_test = QHBoxLayout()
        btn_test = QPushButton("测试连接")
        btn_test.clicked.connect(self._test_conn)
        self.lbl_test = QLabel("")
        row_test.addWidget(btn_test)
        row_test.addWidget(self.lbl_test, 1)
        form.addRow("图片连接", row_test)
        root.addWidget(g1)

        # ---- 组 2：文案对话模型 ----
        g2 = QGroupBox("文案对话模型（第②步 AI 写文案 · 任意 OpenAI 兼容大模型，可配独立 key）")
        form2 = QFormLayout(g2)

        self.ed_text_key = QLineEdit(cfg.get("text_api_key", ""))
        self.ed_text_key.setEchoMode(QLineEdit.Password)
        self.ed_text_key.setPlaceholderText("留空 = 沿用上面的图片 API Key")
        form2.addRow("文案 API Key", self.ed_text_key)

        self.ed_text_base = QLineEdit(cfg.get("text_base_url", ""))
        self.ed_text_base.setPlaceholderText(
            "留空 = 沿用图片接口地址（都没有则用 OpenAI 官方）；任意 OpenAI 兼容地址均可")
        form2.addRow("文案接口地址", self.ed_text_base)

        self.cb_text_model = QComboBox()
        self.cb_text_model.setEditable(True)
        self.cb_text_model.addItems([
            cfg.get("text_model") or "gpt-4o-mini",
            "gpt-4o-mini", "deepseek-chat", "kimi-k2.1-pro", "qwen-plus",
        ])
        self.cb_text_model.setCurrentText(cfg.get("text_model", ""))
        self.cb_text_model.setCurrentIndex(-1 if not cfg.get("text_model") else 0)
        form2.addRow("文案模型", self.cb_text_model)

        row_test2 = QHBoxLayout()
        btn_test2 = QPushButton("测试文案模型")
        btn_test2.clicked.connect(self._test_text)
        self.lbl_test2 = QLabel("")
        row_test2.addWidget(btn_test2)
        row_test2.addWidget(self.lbl_test2, 1)
        form2.addRow("文案连接", row_test2)
        root.addWidget(g2)

        # ---- 组 3：路径与性能 ----
        g3 = QGroupBox("路径与性能")
        form3 = QFormLayout(g3)

        self.ed_skill = QLineEdit(cfg.get("skill_dir", ""))
        btn_skill = QPushButton("浏览…")
        btn_skill.clicked.connect(self._pick_skill)
        row = QHBoxLayout()
        row.addWidget(self.ed_skill, 1)
        row.addWidget(btn_skill)
        form3.addRow("skill 脚本目录", row)

        self.ed_packs = QLineEdit(cfg.get("packs_dir", ""))
        btn_packs = QPushButton("浏览…")
        btn_packs.clicked.connect(self._pick_packs)
        row2 = QHBoxLayout()
        row2.addWidget(self.ed_packs, 1)
        row2.addWidget(btn_packs)
        form3.addRow("项目保存目录", row2)

        self.sp_jobs = QSpinBox()
        self.sp_jobs.setRange(1, 8)
        self.sp_jobs.setValue(int(cfg.get("jobs", 4)))
        form3.addRow("并发数", self.sp_jobs)

        self.cb_quality = QComboBox()
        self.cb_quality.addItems(["low", "medium", "high"])
        self.cb_quality.setCurrentText(cfg.get("quality", "medium"))
        form3.addRow("画质（影响花费）", self.cb_quality)
        root.addWidget(g3)

        tip = QLabel("⚠ API Key 以明文保存在项目根的 config.json，请勿把该文件提交到 git。")
        tip.setStyleSheet("color: #C43D3D;")
        root.addWidget(tip)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def _pick_skill(self):
        d = QFileDialog.getExistingDirectory(self, "选择 skill 脚本目录（含 sticker.py）")
        if d:
            self.ed_skill.setText(d)

    def _pick_packs(self):
        d = QFileDialog.getExistingDirectory(self, "选择项目保存目录")
        if d:
            self.ed_packs.setText(d)

    def _test_conn(self):
        """用当前表单里填的地址/Key 直接探测（不用等保存）。"""
        draft = {"api_key": self.ed_key.text().strip(), "base_url": self.ed_base.text().strip()}
        self.lbl_test.setText("测试中…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.lbl_test.setText(core.test_connection(draft))
        finally:
            QApplication.restoreOverrideCursor()

    def _test_text(self):
        draft = {
            "text_api_key": self.ed_text_key.text().strip(),
            "text_base_url": self.ed_text_base.text().strip(),
            "text_model": self.cb_text_model.currentText().strip(),
            "api_key": self.ed_key.text().strip(),
            "base_url": self.ed_base.text().strip(),
        }
        self.lbl_test2.setText("测试中…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.lbl_test2.setText(core.test_text_connection(draft))
        finally:
            QApplication.restoreOverrideCursor()

    def result_config(self):
        self.cfg.update({
            "api_key": self.ed_key.text().strip(),
            "base_url": self.ed_base.text().strip(),
            "character_model": self.cb_char_model.currentText().strip(),
            "gen_model": self.cb_gen_model.currentText().strip(),
            "text_api_key": self.ed_text_key.text().strip(),
            "text_base_url": self.ed_text_base.text().strip(),
            "text_model": self.cb_text_model.currentText().strip(),
            "skill_dir": self.ed_skill.text().strip(),
            "packs_dir": self.ed_packs.text().strip(),
            "jobs": self.sp_jobs.value(),
            "quality": self.cb_quality.currentText(),
        })
        return self.cfg


# ---------- 主窗口 ----------

def _pack_status_text(p):
    """专辑列表里每套的轻量状态（只看文件系统）。"""
    p = Path(p)
    char = "角色✓" if (p / "character.png").exists() else "角色✗"
    try:
        n = len(core.load_pack_json(p).get("stickers", []))
        copy_ = f"文案{n}张" if n else "文案✗"
    except Exception:
        copy_ = "文案✗"
    gen = len(list((p / "sheets").glob("*.png"))) if (p / "sheets").is_dir() else 0
    built = "合成✓" if (p / "submit" / "表情图").is_dir() else "未合成"
    return f"[{char} · {copy_} · 生成{gen}张 · {built}]"


class AlbumDialog(QDialog):
    """专辑管理器（系列模式）：一个专辑 = 多套同形象表情包。

    专辑就是 packs/ 下的分组目录 + album.json；成员套是普通项目目录。
    新建套会复制同专辑里最新的角色图，系列形象保持一致。
    """

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("专辑管理器（系列模式）")
        self.resize(780, 430)
        v = QVBoxLayout(self)
        split = QHBoxLayout()

        left = QVBoxLayout()
        left.addWidget(QLabel("专辑"))
        self.lst_albums = QListWidget()
        self.lst_albums.currentRowChanged.connect(self._show_album)
        left.addWidget(self.lst_albums, 1)
        row = QHBoxLayout()
        b_na = QPushButton("＋ 新建专辑")
        b_na.clicked.connect(self._new_album)
        row.addWidget(b_na)
        b_dir = QPushButton("打开目录")
        b_dir.clicked.connect(self._open_album_dir)
        row.addWidget(b_dir)
        left.addLayout(row)
        split.addLayout(left, 1)

        right = QVBoxLayout()
        right.addWidget(QLabel("专辑内的套（双击打开）"))
        self.lst_packs = QListWidget()
        self.lst_packs.itemDoubleClicked.connect(lambda _: self._open_pack())
        right.addWidget(self.lst_packs, 1)
        row2 = QHBoxLayout()
        b_np = QPushButton("＋ 在此专辑新建一套")
        b_np.clicked.connect(self._new_pack)
        row2.addWidget(b_np)
        b_op = QPushButton("打开这套")
        b_op.clicked.connect(self._open_pack)
        row2.addWidget(b_op)
        right.addLayout(row2)
        split.addLayout(right, 1)

        v.addLayout(split, 1)
        tip = QLabel("新建的一套自动复制同专辑里最新的角色图（形象一致），风格沿用专辑设定；"
                     "之后走正常的 ①→④ 流程。散装项目不受影响，仍在 packs/ 根目录。")
        tip.setWordWrap(True)
        v.addWidget(tip)
        self._reload()

    def _reload(self):
        keep = self._current_album()
        keep_path = keep["path"] if keep else None
        self.lst_albums.clear()
        self._albums = core.list_albums(self.main.cfg)
        restore = 0
        for i, a in enumerate(self._albums):
            self.lst_albums.addItem(f"{a['meta'].get('name', '?')}（{len(a['packs'])} 套）")
            if a["path"] == keep_path:
                restore = i
        self.lst_albums.setCurrentRow(restore)
        self._show_album(restore)

    def _current_album(self):
        r = self.lst_albums.currentRow()
        if r is None or not (0 <= r < len(getattr(self, "_albums", []))):
            return None
        return self._albums[r]

    def _show_album(self, _row):
        self.lst_packs.clear()
        a = self._current_album()
        if not a:
            return
        for m in a["packs"]:
            it = QListWidgetItem(f"{m['name']}   {_pack_status_text(m['path'])}")
            it.setData(Qt.UserRole, m["path"])
            self.lst_packs.addItem(it)

    def _new_album(self):
        name, ok = QInputDialog.getText(
            self, "新建专辑", "专辑名（1–20 字，同一 IP 的系列归到一起）：")
        if not ok:
            return
        try:
            core.create_album(self.main.cfg, name)
        except Exception as e:
            QMessageBox.warning(self, "建不了", str(e))
            return
        self._reload()
        for i, a in enumerate(self._albums):
            if a["meta"].get("name") == name.strip():
                self.lst_albums.setCurrentRow(i)
                self._show_album(i)

    def _new_pack(self):
        a = self._current_album()
        if not a:
            QMessageBox.information(self, "先选专辑", "左边先选一个专辑，或先「＋ 新建专辑」。")
            return
        name, ok = QInputDialog.getText(
            self, "在专辑里新建一套",
            f"套名（≤8 字，作为表情包名）\n专辑：{a['meta'].get('name', '')}：")
        if not ok:
            return
        name = name.strip()
        if not name or len(name) > 8 or any(c in name for c in BAD_NAME_CHARS):
            QMessageBox.warning(self, "名字不合法", "要 1–8 字、无标点无空格。")
            return
        cands = []
        for m in a["packs"]:
            c = Path(m["path"]) / "character.png"
            if c.exists():
                cands.append((c.stat().st_mtime, m["path"]))
        from_pack = max(cands)[1] if cands else None
        try:
            p, copied = core.new_pack_in_album(self.main.cfg, Path(a["path"]), name, from_pack)
        except Exception as e:
            QMessageBox.warning(self, "建不了", str(e))
            return
        self._reload()
        self.main.load_project(p)
        self.main.goto_step(0)
        self.main.statusBar().showMessage(
            ("已复制系列最新角色图，形象一致；去第①步确认或直接往第②步走。"
             if copied else "专辑里还没有角色图可复制，去第①步生成。"), 8000)
        self.accept()

    def _open_pack(self):
        it = self.lst_packs.currentItem()
        if not it:
            return
        self.main.load_project(Path(it.data(Qt.UserRole)))
        self.accept()

    def _open_album_dir(self):
        a = self._current_album()
        if a:
            QDesktopServices.openUrl(QUrl.fromLocalFile(a["path"]))


class TweakDialog(QDialog):
    """单张微调：以该图本身为参考图 + 微调指令改图（画风构图保持，只调指定方面）。"""

    QUICK = ["表情更夸张", "动作幅度更大", "背景更简洁", "色调更暖",
             "更Q更圆润", "细节更清晰", "增加一点幽默感"]

    def __init__(self, main, item):
        super().__init__(main)
        self.main = main
        self.item = item
        self.setWindowTitle(f"✎ 微调 {item}（画风构图保持，只按指令调整）")
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        img = QLabel()
        img.setAlignment(Qt.AlignCenter)
        img.setMinimumSize(360, 360)
        path = main._thumb_path(item)
        if path and Path(path).exists():
            pm = QPixmap(str(path))
            if not pm.isNull():
                img.setPixmap(pm.scaled(360, 360, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        if img.pixmap() is None or img.pixmap().isNull():
            img.setText("（预览不可用）")
        v.addWidget(img)
        row = QHBoxLayout()
        row.addWidget(QLabel("微调指令："))
        self.ed_inst = QLineEdit()
        self.ed_inst.setPlaceholderText("例如：嘴巴张更大，眼睛眯成月牙，其余保持原样")
        row.addWidget(self.ed_inst, 1)
        v.addLayout(row)
        quick = QHBoxLayout()
        quick.addWidget(QLabel("快捷："))
        for q in self.QUICK:
            b = QPushButton(q)
            b.clicked.connect(lambda _=False, t=q: self._append(t))
            quick.addWidget(b)
        quick.addStretch(1)
        v.addLayout(quick)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok = bb.button(QDialogButtonBox.Ok)
        ok.setText("开始微调（约 $0.05）")
        ok.setProperty("primary", True)
        bb.accepted.connect(self._go)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _append(self, t):
        cur = self.ed_inst.text().strip()
        if t in cur:
            return
        self.ed_inst.setText((cur + "，" if cur else "") + t)

    def _go(self):
        if self.ed_inst.text().strip():
            self.accept()

    def instruction(self):
        return self.ed_inst.text().strip()


class IdeasDialog(QDialog):
    """抽象创意参谋：文案模型出「利于传播的抽象表情」选题，勾选填入灵感提示。"""

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("抽象创意参谋（利于传播的选题）")
        self.resize(760, 500)
        v = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("主题方向（可空）："))
        self.ed_topic = QLineEdit()
        self.ed_topic.setPlaceholderText("如：职场摸鱼 / 大学生期末 / 带娃日常；留空 = AI 自由发挥")
        row.addWidget(self.ed_topic, 1)
        self.btn_go = QPushButton("🧠 出创意")
        self.btn_go.clicked.connect(self._go)
        row.addWidget(self.btn_go)
        v.addLayout(row)
        self.tbl = QTableWidget(0, 3)
        self.tbl.setHorizontalHeaderLabels(["选", "词（1–4字）", "使用场景（传播理由）"])
        self.tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tbl.setColumnWidth(0, 36)
        self.tbl.setColumnWidth(1, 110)
        self.tbl.verticalHeader().setVisible(False)
        v.addWidget(self.tbl, 1)
        # 接口调用日志（默认收起，勾选展开；实时看请求/重试/耗时，排查出创意慢）
        self.api_panel = ApiLogPanel()
        v.addWidget(self.api_panel)
        self.main.register_api_panel(self.api_panel)
        foot = QHBoxLayout()
        self.lbl_state = QLabel(
            "点「出创意」：文案模型会列 ~12 个抽象梗选题，勾选后填入灵感提示，再「AI 生成整套文案」。")
        self.lbl_state.setWordWrap(True)
        foot.addWidget(self.lbl_state, 1)
        b_fill = QPushButton("把选中词填入灵感提示")
        b_fill.clicked.connect(self._fill)
        foot.addWidget(b_fill)
        v.addLayout(foot)

    def _go(self):
        self.btn_go.setEnabled(False)
        self._t0 = time.time()
        if not hasattr(self, "_tick"):
            self._tick = QTimer(self)
            self._tick.timeout.connect(self._tick_elapsed)
        self._tick.start(1000)
        self._tick_elapsed()
        self.worker = Worker(core.ai_ideas, self.main.cfg, self.ed_topic.text().strip())
        self.worker.done.connect(self._on_ideas)
        self.worker.failed.connect(self._on_ideas_fail)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def _tick_elapsed(self):
        sec = int(time.time() - self._t0)
        tip = "思考型模型（DeepSeek-R1 等）可能要 1–5 分钟，请耐心等；可勾选「显示后台调用日志」看进度"
        if sec < 45:
            self.lbl_state.setText(f"AI 正在出创意…（已 {sec} 秒）")
        else:
            self.lbl_state.setText(f"AI 正在出创意…（已 {sec} 秒）——{tip}")

    def done(self, r):
        # 所有关闭路径（点 X / 取消 / 填入灵感提示）的必经点：先注销日志面板防僵尸，
        # worker 还在跑就断开回调让它自然结束（请求本身无法中断，忽略即可）
        self.main.unregister_api_panel(self.api_panel)
        if hasattr(self, "_tick"):
            self._tick.stop()
        w = getattr(self, "worker", None)
        if w is not None and w.isRunning():
            try:
                w.done.disconnect(self._on_ideas)
                w.failed.disconnect(self._on_ideas_fail)
            except (TypeError, RuntimeError):
                pass
        super().done(r)

    def _on_ideas(self, ideas):
        self.btn_go.setEnabled(True)
        if hasattr(self, "_tick"):
            self._tick.stop()
        sec = int(time.time() - self._t0)
        self.tbl.setRowCount(0)
        for i, it in enumerate(ideas):
            r = self.tbl.rowCount()
            self.tbl.insertRow(r)
            chk = QTableWidgetItem()
            chk.setCheckState(Qt.Checked if i < 4 else Qt.Unchecked)
            self.tbl.setItem(r, 0, chk)
            self.tbl.setItem(r, 1, QTableWidgetItem(it["word"]))
            self.tbl.setItem(r, 2, QTableWidgetItem(f"{it['scene']}（{it['why']}）"))
        self.lbl_state.setText(f"共 {len(ideas)} 条，用时 {sec} 秒。选好后点右下按钮填入灵感提示。")

    def _on_ideas_fail(self, msg):
        self.btn_go.setEnabled(True)
        if hasattr(self, "_tick"):
            self._tick.stop()
        self.lbl_state.setText(f"❌ {msg}")

    def _fill(self):
        words = []
        for r in range(self.tbl.rowCount()):
            it0 = self.tbl.item(r, 0)
            if it0 and it0.checkState() == Qt.Checked:
                words.append(self.tbl.item(r, 1).text())
        if not words:
            self.lbl_state.setText("先在左列勾选想要的词。")
            return
        topic = self.ed_topic.text().strip()
        hint = (f"{topic}；" if topic else "") + "抽象梗方向，重点覆盖这些词：" + "、".join(words)
        self.main.ed_hint.setText(hint)
        self.accept()


class MainWindow(QMainWindow):
    api_line = Signal(str)   # core 线程里的日志 → UI 线程

    def __init__(self):
        super().__init__()
        self.setWindowTitle("表情包工坊 · ray-sticker-shop")
        self.resize(1150, 860)
        self.cfg = core.load_config()
        self.sticker = None
        self.pack_dir = None       # 当前项目目录（含 pack.json）
        self.worker = None
        self.movies = []           # 防 QMovie 被 GC
        self.gen_done = 0
        self.gen_total = 0
        self._busy_step = None     # 当前有后台任务的步骤号
        self._busy_t0 = 0.0        # 该任务开始时刻（算已用时/预计剩余）
        self.last_fails = []       # 最近一次 check 的 FAIL 列表

        self._build_menu()
        self._reload_sticker()

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 12, 16, 8)
        root.setSpacing(12)

        # 顶部步骤导航 = 进度总览：每颗按钮两行（步骤名 + 该步状态），点击跳转
        nav = QHBoxLayout()
        self.step_btns = []
        for i, name in enumerate(STEP_NAMES):
            b = QPushButton(f"{name}\n")
            b.setCheckable(True)
            b.setMinimumHeight(48)
            b.setMinimumWidth(215)
            b.setStyleSheet(_chip_ss("pending"))
            b.clicked.connect(lambda _, idx=i: self.goto_step(idx))
            nav.addWidget(b)
            self.step_btns.append(b)
        nav.addStretch(1)
        root.addLayout(nav)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_character())
        self.stack.addWidget(self._page_pack())
        self.stack.addWidget(self._page_gen())
        self.stack.addWidget(self._page_delivery())
        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.lbl_proj = QLabel("未打开项目")
        self.lbl_cost = QLabel("")
        sb = self.statusBar()
        sb.addWidget(self.lbl_proj)
        sb.addPermanentWidget(self.lbl_cost)

        if not self.cfg.get("api_key"):
            sb.showMessage("未配置 API Key：设置→参数设置 填写，或用「无 key 手动出图」模式", 10000)
        self.goto_step(0)
        self._refresh_overview()
        core.add_log_listener(self.api_line.emit)
        self.api_line.connect(self._on_api_line)
        self.api_panels = [self.api_log_panel_char, self.api_log_panel_gen]

        # 每秒刷新一次长任务的已用时/预计剩余
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(1000)

        # 断点继续：启动时自动恢复最近一次的项目
        self._resume_last()

    def _on_api_line(self, line):
        for p in self.api_panels:
            p.append(line)

    def register_api_panel(self, p):
        """子对话框把自己的日志面板挂进分发列表（挂起期间实时收日志）。"""
        if p not in self.api_panels:
            self.api_panels.append(p)

    def unregister_api_panel(self, p):
        if p in self.api_panels:
            self.api_panels.remove(p)

    def _resume_last(self):
        """启动时自动加载最近项目；没有就停在初始页。"""
        for s in self.cfg.get("recent_projects") or []:
            if (Path(s) / "pack.json").exists():
                self.load_project(Path(s))
                self.statusBar().showMessage(
                    f"已恢复上次项目：{Path(s).name}（断点继续；文件 → 最近项目 可切换）", 10000)
                return
        if self.cfg.get("recent_projects"):
            self.statusBar().showMessage(
                "上次的项目目录已不存在，请「文件 → 打开项目」重新选择", 10000)

    def _rebuild_recent_menu(self):
        m = self.m_recent
        m.clear()
        rec = self.cfg.get("recent_projects") or []
        if not rec:
            a = m.addAction("（暂无历史）")
            a.setEnabled(False)
            return
        for s in rec[:8]:
            act = m.addAction(f"{Path(s).name}  —  {s}")
            act.triggered.connect(lambda _, p=s: self._open_recent(p))

    def _open_recent(self, p):
        if not (Path(p) / "pack.json").exists():
            QMessageBox.warning(self, "项目不存在", f"{p}\n目录已被移动或删除。")
            self._rebuild_recent_menu()
            return
        self.load_project(Path(p))

    # ----- 菜单 -----

    def _build_menu(self):
        m_file = self.menuBar().addMenu("文件")
        act_new = m_file.addAction("新建项目…")
        act_new.triggered.connect(self.new_project)
        act_open = m_file.addAction("打开项目…")
        act_open.triggered.connect(self.open_project)
        self.m_recent = m_file.addMenu("最近项目")
        self._rebuild_recent_menu()
        m_file.addSeparator()
        act_albums = m_file.addAction("专辑管理器…")
        act_albums.triggered.connect(self._open_albums)
        act_quit = m_file.addAction("退出")
        act_quit.triggered.connect(self.close)

        m_set = self.menuBar().addMenu("设置")
        act_cfg = m_set.addAction("参数设置…")
        act_cfg.triggered.connect(self.open_settings)

        m_help = self.menuBar().addMenu("帮助")
        act_doc = m_help.addAction("使用说明")
        act_doc.triggered.connect(self.show_help)
        act_about = m_help.addAction("关于")
        act_about.triggered.connect(
            lambda: QMessageBox.about(
                self, "关于",
                "表情包工坊桌面版\n\n基于 imraywang/ray-sticker-shop skill 的图形界面。\n"
                "生成、压缩、检查逻辑全部复用 skill 脚本。"))

    def _reload_sticker(self):
        try:
            self.sticker = core.load_sticker(self.cfg["skill_dir"])
        except FileNotFoundError as e:
            QMessageBox.critical(self, "缺 skill 脚本", str(e))

    # ----- 步骤切换 -----

    def goto_step(self, idx):
        self.stack.setCurrentIndex(idx)
        for i, b in enumerate(self.step_btns):
            b.setChecked(i == idx)
        if idx == 2:
            self._refresh_thumbs()  # 进第③步刷新缩略图墙

    def _next_step(self):
        self.goto_step(min(self.stack.currentIndex() + 1, 3))

    def _prev_step(self):
        self.goto_step(max(self.stack.currentIndex() - 1, 0))

    # ----- 进度总览（顶部四格）-----

    def _compute_overview(self):
        """按项目目录的真实文件状态算四步进度：[(状态, 说明)] × 4。"""
        if not self.pack_dir:
            return [("pending", "未打开项目")] * 4
        try:
            n = len(core.load_pack_json(self.pack_dir).get("stickers", []))
        except Exception:
            n = 0

        # ① 角色
        s1 = ("done", "角色图 ✓") if (self.pack_dir / "character.png").exists() \
            else ("pending", "未生成角色图")

        # ② 文案
        if self._busy_step == 1:
            s2 = ("run", "AI 写文案中…")
        else:
            s2 = ("done", f"文案 {n} 张 ✓") if n else ("pending", "未保存文案")

        # ③ 生成（精灵图 + 素材）
        sheets = len(list((self.pack_dir / "sheets").glob("*.png"))) \
            if (self.pack_dir / "sheets").exists() else 0
        assets = len(list((self.pack_dir / "assets_raw").glob("*.png"))) \
            if (self.pack_dir / "assets_raw").exists() else 0
        want_assets = self.cb_assets.isChecked() if hasattr(self, "cb_assets") else True
        if self._busy_step == 2 and self.gen_total:
            s3 = ("run", f"生成中 {self.gen_done}/{self.gen_total}")
        elif sheets == 0:
            s3 = ("pending", "还没生成")
        elif sheets >= n and (not want_assets or assets >= 5):
            s3 = ("done", f"精灵图 {sheets}/{n} ✓ · 素材 {assets}/5")
        else:
            s3 = ("partial", f"精灵图 {sheets}/{n} · 素材 {assets}/5")

        # ④ 合成/检查/交付
        gif_dir = self.pack_dir / "submit" / "表情图"
        gifs = len(list(gif_dir.glob("*.gif"))) if gif_dir.exists() else 0
        zip_ok = (self.pack_dir / "交付给客户.zip").exists()
        if self._busy_step == 3:
            s4 = ("run", "处理中…")
        elif self.last_fails:
            s4 = ("error", f"检查 FAIL {len(self.last_fails)} 项")
        elif zip_ok and gifs >= n:
            s4 = ("done", f"GIF {gifs}/{n} ✓ · 交付包已出")
        elif gifs:
            s4 = ("partial", f"GIF {gifs}/{n} · 未出交付包")
        else:
            s4 = ("pending", "未合成")
        return [s1, s2, s3, s4]

    def _refresh_overview(self):
        if not hasattr(self, "step_btns"):
            return
        for i, (level, text) in enumerate(self._compute_overview()):
            b = self.step_btns[i]
            name = b.text().split("\n", 1)[0]
            b.setText(f"{name}\n{text}")
            b.setStyleSheet(_chip_ss(level))

    def _worker_alive(self):
        """线程是否真在跑。Worker 被 deleteLater 后 C++ 对象已销毁，
        直接调 isRunning() 会抛 RuntimeError——这里兜住并清掉僵尸引用。"""
        try:
            if self.worker is None:
                return False
            return self.worker.isRunning()
        except RuntimeError:
            self.worker = None  # C++ 对象已回收，只剩 Python 空壳
            return False

    def _tick(self):
        """长任务每秒刷新：① 显示已用时，③ 显示已用时+预计剩余。"""
        if not (self._worker_alive() and self._busy_step is not None):
            return
        el = time.monotonic() - self._busy_t0
        if self._busy_step == 0:
            self.char_status.setText(
                f"⏳ 生成中… 已用 {_fmt_mmss(el)}（一张约 1–2 分钟，别关窗口）")
        elif self._busy_step == 1:
            self.statusBar().showMessage(f"AI 正在写文案… 已用 {_fmt_mmss(el)}")
        elif self._busy_step == 2:
            txt = f"⏳ 已用 {_fmt_mmss(el)}"
            if self.gen_done and self.gen_total > self.gen_done:
                eta = (el / self.gen_done) * (self.gen_total - self.gen_done)
                txt += f" · 预计还需 ~{_fmt_mmss(eta)}"
            txt += f" · 完成 {self.gen_done}/{self.gen_total}"
            self.lbl_gen_stat.setText(txt)
        elif self._busy_step == 3:
            self.statusBar().showMessage(f"处理中… 已用 {_fmt_mmss(el)}")

    # ----- ① 定角色 -----

    def _page_character(self):
        w = QWidget()
        v = QVBoxLayout(w)

        row0 = QHBoxLayout()
        row0.addWidget(QLabel("第 1 步：上传照片，生成卡通角色图。这张图决定整套表情的形象。"))
        row0.addStretch(1)
        v.addLayout(row0)

        mid = QHBoxLayout()
        self.drop = DropLabel()
        self.drop.pathSelected.connect(lambda p: self.lbl_photo.setText(p))
        self.drop.setMinimumWidth(340)
        mid.addWidget(self.drop, 2)

        side = QVBoxLayout()
        btn_pick = QPushButton("浏览照片…")
        btn_pick.clicked.connect(self._pick_photo)
        side.addWidget(btn_pick)
        self.lbl_photo = QLineEdit()
        self.lbl_photo.setReadOnly(True)
        self.lbl_photo.setPlaceholderText("未选择照片")
        side.addWidget(self.lbl_photo)
        form = QFormLayout()
        self.cb_char_style = QComboBox()
        self.cb_char_style.setEditable(True)
        self.cb_char_style.addItems(STYLES)
        self.cb_char_style.setCurrentText(self.cfg.get("style", STYLES[0]))
        self.cb_char_style.setToolTip(
            "默认第一项是「熊猫头式情绪原型」：大头、表情浓度拉满、自带态度的脸。\n"
            "这张基准脸会传导到全套每张表情——想要温和治愈风就换可爱 Q 版。")
        form.addRow("角色风格", self.cb_char_style)
        self.ed_char_desc = QLineEdit()
        self.ed_char_desc.setPlaceholderText(
            "可选，照片没画到的细节：如「戴黑框眼镜、灰色卫衣、头顶一撮呆毛」")
        self.ed_char_desc.setToolTip(
            "补充穿搭/配饰/气质等照片上看不到的信息，会融合进角色设定；留空 = 纯照片转绘。\n"
            "会随项目保存，重新生成角色图时自动带出。")
        form.addRow("角色描述", self.ed_char_desc)
        side.addLayout(form)
        self.btn_char = QPushButton("生成角色图")
        self.btn_char.setProperty("primary", True)
        self.btn_char.clicked.connect(self.make_character)
        side.addWidget(self.btn_char)
        self.char_status = QLabel("")
        self.char_status.setWordWrap(True)
        side.addWidget(self.char_status)
        self.api_log_panel_char = ApiLogPanel()
        side.addWidget(self.api_log_panel_char)
        side.addStretch(1)
        mid.addLayout(side, 1)
        v.addLayout(mid, 1)

        bottom = QHBoxLayout()
        self.lbl_char_preview = QLabel("角色图预览")
        self.lbl_char_preview.setAlignment(Qt.AlignCenter)
        self.lbl_char_preview.setMinimumSize(280, 280)
        self.lbl_char_preview.setStyleSheet(
            f"QLabel{{border: 1px solid {theme.CARD_BORDER}; border-radius: 12px;"
            f"background: {theme.CARD_BG}; color: #B3ADA1;}}")
        bottom.addWidget(self.lbl_char_preview, 1)
        v.addLayout(bottom, 1)

        foot = QHBoxLayout()
        tip = QLabel("不满意就点「生成角色图」重抽；满意再下一步。这张图是整套一致性的锚。")
        tip.setWordWrap(True)
        foot.addWidget(tip, 1)
        btn_next = QPushButton("满意，下一步 →")
        btn_next.clicked.connect(self._next_step)
        foot.addWidget(btn_next)
        v.addLayout(foot)
        return w

    def _pick_photo(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择照片", "", "图片 (*.jpg *.jpeg *.png *.webp)")
        if p:
            self.drop.set_photo(p)

    def make_character(self):
        if not self._require_project():
            return
        photo = self.drop.photo()
        if not photo:
            QMessageBox.warning(self, "缺照片", "请先上传或拖入一张照片。")
            return
        out = self.pack_dir / "character.png"
        style = self.cb_char_style.currentText().strip() or STYLES[0]
        desc = self.ed_char_desc.text().strip()
        self.char_status.setText("⏳ 提交生成…")
        self._run("正在生成角色图…", core.make_character, self.sticker, self.cfg,
                  photo, out, style, desc, step=0, on_done=self._on_character_done,
                  on_fail=lambda m: self.char_status.setText(f"❌ 生成失败，可重试：{m[:120]}"))

    def _on_character_done(self, result):
        self.char_status.setText("✅ 角色图已生成，请检查形象是否还原。")
        pm = QPixmap(result["out"])
        self.lbl_char_preview.setPixmap(
            pm.scaled(self.lbl_char_preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.refresh_cost()
        self._refresh_overview()

    # ----- ② 写文案 -----

    def _page_pack(self):
        w = QWidget()
        v = QVBoxLayout(w)

        # AI 辅助写文案
        ai_row = QHBoxLayout()
        ai_row.addWidget(QLabel("AI 写文案："))
        self.ed_hint = QLineEdit()
        self.ed_hint.setPlaceholderText(
            "可选灵感：主题/人设/卖点，如「无敌战斗猫，反差萌，日常吐槽」；留空让 AI 自由发挥")
        ai_row.addWidget(self.ed_hint, 1)
        self.btn_ai = QPushButton("✨ AI 生成整套文案")
        self.btn_ai.setProperty("primary", True)
        self.btn_ai.clicked.connect(self.ai_copy)
        ai_row.addWidget(self.btn_ai)
        self.btn_ideas = QPushButton("💡 抽象创意参谋")
        self.btn_ideas.setToolTip("让文案模型列出利于传播的抽象梗选题，勾选后填入灵感提示")
        self.btn_ideas.clicked.connect(self._open_ideas)
        ai_row.addWidget(self.btn_ideas)
        v.addLayout(ai_row)

        meta_box = QGroupBox("专辑信息")
        form = QFormLayout(meta_box)

        self.ed_name = QLineEdit()
        self.ct_name = QLabel("0/8")
        self.ed_name.textChanged.connect(
            lambda t: self.ct_name.setText(f"{len(t.strip())}/8"))
        form.addRow("表情名称（≤8字无标点）", _counter_row(self.ed_name, self.ct_name))

        self.ed_intro = QTextEdit()
        self.ed_intro.setMaximumHeight(56)
        self.ed_intro.setPlaceholderText("讲角色的性格或一个小故事")
        self.ct_intro = QLabel("0/80")
        self.ed_intro.textChanged.connect(
            lambda: self.ct_intro.setText(f"{len(self.ed_intro.toPlainText())}/80"))
        form.addRow("表情介绍（≤80字）", _counter_row(self.ed_intro, self.ct_intro))

        self.ed_copyright = QLineEdit()
        self.ed_copyright.setPlaceholderText("设计师或工作室名")
        self.ct_cr = QLabel("0/10")
        self.ed_copyright.textChanged.connect(
            lambda t: self.ct_cr.setText(f"{len(t.strip())}/10"))
        form.addRow("版权信息（≤10字）", _counter_row(self.ed_copyright, self.ct_cr))

        self.ed_reward = QLineEdit()
        self.ed_reward.setPlaceholderText("5–15 字，和表情强相关，留空=不做赞赏图")
        self.ct_rw = QLabel("0/15")
        self.ed_reward.textChanged.connect(
            lambda t: self.ct_rw.setText(f"{len(t.strip())}/15"))
        form.addRow("赞赏引导语", _counter_row(self.ed_reward, self.ct_rw))

        gen_box = QGroupBox("生成参数")
        gen_form = QFormLayout(gen_box)
        self.cb_pack_style = QComboBox()
        self.cb_pack_style.setEditable(True)
        self.cb_pack_style.addItems(STYLES)
        gen_form.addRow("角色风格补充", self.cb_pack_style)
        self.sp_ms = QSpinBox()
        self.sp_ms.setRange(30, 600)
        self.sp_ms.setSuffix(" ms/帧")
        gen_form.addRow("帧间隔", self.sp_ms)
        self.cb_bg = QComboBox()
        self.cb_bg.addItems(["transparent", "opaque"])
        gen_form.addRow("背景", self.cb_bg)

        # 两个表单并排：把垂直空间让给下面的表情文案表格
        top_boxes = QHBoxLayout()
        top_boxes.addWidget(meta_box, 2)
        top_boxes.addWidget(gen_box, 1)
        v.addLayout(top_boxes)

        sticker_box = QGroupBox("表情文案（8–24 张；含义词 ≤4 字且不重复；动作写具体身体动作，英文）")
        sv = QVBoxLayout(sticker_box)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["#", "含义词", "配字", "动作（英文）"])
        self.table.setMinimumHeight(320)
        self.table.verticalHeader().setDefaultSectionSize(34)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.Stretch)
        sv.addWidget(self.table)
        brow = QHBoxLayout()
        btn_add = QPushButton("+ 添加一张")
        btn_add.clicked.connect(lambda: self._add_table_row(None))
        brow.addWidget(btn_add)
        btn_del = QPushButton("- 删除选中")
        btn_del.clicked.connect(self._del_table_row)
        brow.addWidget(btn_del)
        brow.addStretch(1)
        self.lbl_validate = QLabel("")
        self.lbl_validate.setStyleSheet("color: #C43D3D;")
        brow.addWidget(self.lbl_validate, 1)
        btn_save = QPushButton("保存 pack.json")
        btn_save.clicked.connect(self.save_pack)
        brow.addWidget(btn_save)
        sv.addLayout(brow)
        v.addWidget(sticker_box, 1)

        foot = QHBoxLayout()
        btn_prev = QPushButton("← 上一步")
        btn_prev.clicked.connect(self._prev_step)
        foot.addWidget(btn_prev)
        foot.addStretch(1)
        btn_next = QPushButton("下一步，去生成 →")
        btn_next.clicked.connect(lambda: (self.save_pack(silent=True), self._next_step()))
        foot.addWidget(btn_next)
        v.addLayout(foot)
        return w

    def ai_copy(self):
        """调文案对话模型产整套初稿，填进表单，人工检查后再保存。"""
        if not self._require_project():
            return
        if not (self.cfg.get("text_model") or self.cfg.get("api_key")):
            QMessageBox.information(
                self, "先配文案模型",
                "设置 → 参数设置 → 「文案对话模型」里填模型名和 Key（可用和图片不同的账号）。")
            return
        self.btn_ai.setEnabled(False)
        self.lbl_validate.setText("⏳ AI 正在写文案…（约 10-30 秒）")
        self._run("AI 正在写文案…", core.ai_copywriting, self.cfg,
                  self.ed_hint.text().strip(), self.cb_pack_style.currentText().strip(),
                  step=1, on_done=self._on_ai_copy,
                  on_fail=lambda m: self.lbl_validate.setText(f"❌ AI 文案失败：{m[:160]}"))

    def _on_ai_copy(self, r):
        self.btn_ai.setEnabled(True)
        self.ed_name.setText(r.get("name", ""))
        self.ed_intro.setPlainText(r.get("intro", ""))
        if r.get("reward_line"):
            self.ed_reward.setText(r["reward_line"])
        self.table.setRowCount(0)
        for s in r.get("stickers", []):
            self._add_table_row(s)
        fails = core.validate_pack(self.collect_pack())
        if fails:
            self.lbl_validate.setText(f"AI 初稿已填入，但还有 {len(fails)} 处要改：{fails[0]}（改完保存）")
        else:
            self.lbl_validate.setText("✅ AI 初稿已填入并通过校验，人工过目后点「保存 pack.json」")
        self._refresh_overview()

    def _add_table_row(self, sticker):
        r = self.table.rowCount()
        if r >= 24:
            return
        self.table.insertRow(r)
        num = QTableWidgetItem(str(r + 1))
        num.setFlags(num.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(r, 0, num)
        if sticker:
            self.table.setItem(r, 1, QTableWidgetItem(sticker.get("word", "")))
            self.table.setItem(r, 2, QTableWidgetItem(sticker.get("caption") or ""))
            self.table.setItem(r, 3, QTableWidgetItem(sticker.get("action", "")))
        else:
            self.table.setItem(r, 3, QTableWidgetItem(""))

    def _del_table_row(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)
        for r in range(self.table.rowCount()):
            self.table.item(r, 0).setText(str(r + 1))

    def collect_pack(self):
        pack = {
            "name": self.ed_name.text().strip(),
            "intro": self.ed_intro.toPlainText().strip(),
            "copyright": self.ed_copyright.text().strip(),
            "reward_line": self.ed_reward.text().strip(),
            "character": "character.png",
            "character_desc": self.ed_char_desc.text().strip(),
            "style": self.cb_pack_style.currentText().strip(),
            "frame_ms": self.sp_ms.value(),
            "background": self.cb_bg.currentText(),
            "stickers": [],
        }
        for r in range(self.table.rowCount()):
            def cell(c, r=r):
                it = self.table.item(r, c)
                return it.text().strip() if it else ""
            pack["stickers"].append({
                "word": cell(1), "caption": cell(2), "action": cell(3) or "waves hello"})
        return pack

    def apply_pack(self, pack):
        self.ed_name.setText(pack.get("name", ""))
        self.ed_intro.setPlainText(pack.get("intro", ""))
        self.ed_copyright.setText(pack.get("copyright", ""))
        self.ed_reward.setText(pack.get("reward_line", ""))
        self.cb_pack_style.setCurrentText(pack.get("style", ""))
        self.ed_char_desc.setText(pack.get("character_desc", ""))
        self.sp_ms.setValue(int(pack.get("frame_ms", 120)))
        self.cb_bg.setCurrentText(pack.get("background", "transparent"))
        self.table.setRowCount(0)
        for s in pack.get("stickers", []):
            self._add_table_row(s)

    def save_pack(self, silent=False):
        if not self._require_project():
            return False
        pack = self.collect_pack()
        fails = core.validate_pack(pack)
        self.lbl_validate.setText("；".join(fails[:3]) + ("…" if len(fails) > 3 else ""))
        if fails and not silent:
            QMessageBox.warning(self, "还有问题要先改", "\n".join(fails))
            return False
        core.save_pack_json(self.pack_dir, pack)
        if not silent:
            self.lbl_validate.setText("✅ 已保存" if not fails else f"已保存草稿（{len(fails)} 处待改）")
        self._refresh_overview()
        return True

    # ----- ③ 生成 -----

    def _page_gen(self):
        w = QWidget()
        v = QVBoxLayout(w)
        row0 = QHBoxLayout()
        row0.addWidget(QLabel("第 3 步：先预估花费，确认后开始生成。已生成过的图会自动跳过。"))
        row0.addStretch(1)
        v.addLayout(row0)

        btns = QHBoxLayout()
        self.btn_dry = QPushButton("① 预估花费")
        self.btn_dry.clicked.connect(self.dry_run)
        btns.addWidget(self.btn_dry)
        self.btn_gen = QPushButton("② 开始生成")
        self.btn_gen.setProperty("primary", True)
        self.btn_gen.clicked.connect(self.start_gen)
        btns.addWidget(self.btn_gen)
        self.lbl_plan = QLabel("还没预估")
        btns.addWidget(self.lbl_plan, 1)
        v.addLayout(btns)

        opt = QHBoxLayout()
        self.cb_assets = QCheckBox("同时生成配套素材（封面/图标/横幅/赞赏图）")
        self.cb_assets.setChecked(True)
        opt.addWidget(self.cb_assets)
        opt.addStretch(1)
        opt.addWidget(QLabel("重抽第几张："))
        self.ed_redo = QLineEdit()
        self.ed_redo.setPlaceholderText("如 3,7（留空=只补缺失的）")
        self.ed_redo.setMaximumWidth(180)
        opt.addWidget(self.ed_redo)
        v.addLayout(opt)

        self.bar = QProgressBar()
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        v.addWidget(self.bar)
        self.lbl_gen_stat = QLabel("")
        v.addWidget(self.lbl_gen_stat)
        # 实时缩略图墙：每生成完一张立刻上墙，双击看大图
        thumb_row = QHBoxLayout()
        thumb_row.addWidget(QLabel("已生成（双击看大图）："))
        thumb_row.addStretch(1)
        v.addLayout(thumb_row)
        self.thumb_list = QListWidget()
        self.thumb_list.setViewMode(QListWidget.IconMode)
        self.thumb_list.setFlow(QListWidget.LeftToRight)
        self.thumb_list.setWrapping(False)
        self.thumb_list.setIconSize(QSize(112, 112))
        self.thumb_list.setFixedHeight(150)
        self.thumb_list.setSpacing(6)
        self.thumb_list.setUniformItemSizes(True)
        self.thumb_list.itemDoubleClicked.connect(self._open_thumb)
        self.thumb_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.thumb_list.customContextMenuRequested.connect(self._thumb_menu)
        v.addWidget(self.thumb_list)
        self.gen_log = QPlainTextEdit()
        self.gen_log.setReadOnly(True)
        self.gen_log.setObjectName("consoleLog")
        v.addWidget(self.gen_log, 1)
        self.api_log_panel_gen = ApiLogPanel()
        v.addWidget(self.api_log_panel_gen)

        nokey = QHBoxLayout()
        btn_prompts = QPushButton("无 Key？查看出图提示词")
        btn_prompts.clicked.connect(self.show_prompts)
        nokey.addWidget(btn_prompts)
        btn_open_sheets = QPushButton("打开 sheets 目录")
        btn_open_sheets.clicked.connect(
            lambda: self._open_path(self.pack_dir / "sheets" if self.pack_dir else None))
        nokey.addWidget(btn_open_sheets)
        nokey.addStretch(1)
        v.addLayout(nokey)

        foot = QHBoxLayout()
        btn_prev = QPushButton("← 上一步")
        btn_prev.clicked.connect(self._prev_step)
        foot.addWidget(btn_prev)
        foot.addStretch(1)
        btn_next = QPushButton("生成完，去合成 →")
        btn_next.clicked.connect(self._next_step)
        foot.addWidget(btn_next)
        v.addLayout(foot)
        return w

    def dry_run(self):
        if not self._require_ready():
            return
        self._run("正在统计…", core.dry_run, self.sticker, self.cfg,
                  self.pack_dir, self.cb_assets.isChecked(), step=2,
                  on_done=lambda r: self.lbl_plan.setText(
                      f"要生成 {r['count']} 张，按官方单价约 ${r['usd']}（重抽另算）"))

    def start_gen(self):
        if not self._require_ready():
            return
        if not self.save_pack(silent=True):
            return
        fails = core.validate_pack(self.collect_pack())
        if fails:
            QMessageBox.warning(self, "文案还有问题，先回第 2 步改", "\n".join(fails[:8]))
            return
        if not (self.pack_dir / "character.png").exists():
            QMessageBox.warning(self, "缺角色图", "请先在第 1 步生成角色图。")
            return
        self.gen_log.clear()
        self.gen_done = 0
        self.gen_total = 0
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.lbl_gen_stat.setText("⏳ 提交中…")
        redo = [x.strip() for x in self.ed_redo.text().replace("，", ",").split(",") if x.strip()]
        self._run("生成中…", core.gen_pack, self.sticker, self.cfg, self.pack_dir,
                  self.cb_assets.isChecked(), redo, step=2,
                  with_progress=True, progress_slot=self._on_gen_progress,
                  on_done=self._on_gen_done,
                  on_fail=lambda m: (self.gen_log.appendPlainText(f"❌ {m}"),
                                     self.lbl_gen_stat.setText("")))

    # ----- 第③步 实时缩略图墙 -----

    def _thumb_path(self, name):
        """按文件名定位：两位数字开头是精灵图，其余是配套素材。"""
        if not self.pack_dir:
            return None
        sub = "sheets" if name[:2].isdigit() else "assets_raw"
        p = self.pack_dir / sub / name
        return p if p.exists() else None

    def _add_thumb(self, name):
        """生成完一张就立刻上墙；重抽同名图原位更新。"""
        p = self._thumb_path(name)
        if not p:
            return
        reader = QImageReader(str(p))  # 读时就缩到 112px，不整张解码 2048² 大图
        reader.setScaledSize(QSize(112, 112))
        img = reader.read()
        if img.isNull():
            return
        icon = QIcon(QPixmap.fromImage(img))
        exist = self.thumb_list.findItems(name, Qt.MatchExactly)
        if exist:
            exist[0].setIcon(icon)
            self.thumb_list.scrollToItem(exist[0])
            return
        item = QListWidgetItem(icon, name)
        item.setToolTip(f"{name}（双击看大图）")
        self.thumb_list.addItem(item)
        self.thumb_list.scrollToBottom()

    def _refresh_thumbs(self):
        """进第③步时把已生成的精灵图/素材先铺上（断点继续也能看到图）。"""
        if not hasattr(self, "thumb_list"):
            return
        self.thumb_list.clear()
        if not self.pack_dir:
            return
        for sub in ("sheets", "assets_raw"):
            d = self.pack_dir / sub
            if d.is_dir():
                for f in sorted(d.glob("*.png")):
                    self._add_thumb(f.name)

    def _open_thumb(self, item):
        p = self._thumb_path(item.text())
        if p:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def _thumb_menu(self, pos):
        it = self.thumb_list.itemAt(pos)
        if it is None:
            return
        menu = QMenu(self)
        act_tweak = menu.addAction("✎ 微调这张…")
        act_open = menu.addAction("🔍 看大图")
        chosen = menu.exec(self.thumb_list.mapToGlobal(pos))
        if chosen is act_open:
            self._open_thumb(it)
        elif chosen is act_tweak:
            self._tweak_sheet(it.text())

    def _tweak_sheet(self, item):
        dlg = TweakDialog(self, item)
        if dlg.exec() != QDialog.Accepted or not dlg.instruction():
            return
        inst = dlg.instruction()

        def done(r):
            self._add_thumb(r["item"])  # 原位更新缩略图
            self.gen_log.appendPlainText(f"✅ {r['item']} 微调完成（{r['bytes'] // 1024}KB）")
            self.statusBar().showMessage(f"✅ {r['item']} 微调完成", 8000)

        self._run(f"微调 {item} 中…", core.tweak_sheet, self.sticker, self.cfg,
                  self.pack_dir, item, inst, step=2, on_done=done,
                  on_fail=lambda m: QMessageBox.critical(self, "微调失败", m))

    def _on_gen_progress(self, item, kind, msg):
        if kind == "total":
            total = int(msg)
            self.gen_total = total
            self.bar.setRange(0, max(total, 1))
        elif kind == "count":
            self.gen_done = int(msg.split("/")[0])
            self.bar.setValue(self.gen_done)
            self._refresh_overview()
        else:
            mark = {"ok": "✅", "fail": "❌", "skip": "⏭️"}.get(kind, "")
            self.gen_log.appendPlainText(f"{mark} {item or ''} {msg}")
            if kind == "ok" and item:
                self._add_thumb(item)  # 实时上墙
            self._refresh_overview()

    def _on_gen_done(self, result):
        el = _fmt_mmss(time.monotonic() - self._busy_t0) if self._busy_t0 else ""
        if result["total"] == 0:
            self.gen_log.appendPlainText("没有需要生成的新图。要重抽某几张，填「重抽第几张」再点开始。")
        else:
            tail = f"，失败 {len(result['errors'])} 张（重跑只补缺的）" if result["errors"] else ""
            self.gen_log.appendPlainText(
                f"完成：{result['total'] - len(result['errors'])}/{result['total']}{tail}"
                + (f" · 总用时 {el}" if el else ""))
        self.lbl_gen_stat.setText(f"结束 · 总用时 {el}" if el else "")
        self.lbl_plan.setText(f"本目录累计花费约 ${result['cost']:.2f}")
        self.refresh_cost()
        self._refresh_overview()

    def show_prompts(self):
        if not self._require_ready():
            return
        try:
            items = core.get_prompts(self.sticker, self.pack_dir)
        except Exception as e:
            QMessageBox.warning(self, "出错了", str(e))
            return
        PromptsDialog(items, self).exec()

    # ----- ④ 合成 · 检查 · 交付 -----

    def _page_delivery(self):
        w = QWidget()
        v = QVBoxLayout(w)
        row0 = QHBoxLayout()
        row0.addWidget(QLabel("第 4 步：合成 GIF 和投稿包，跑规范检查（FAIL 必须清零），人工确认后交付。"))
        row0.addStretch(1)
        v.addLayout(row0)

        btns = QHBoxLayout()
        self.btn_build = QPushButton("合成 build")
        self.btn_build.setProperty("primary", True)
        self.btn_build.clicked.connect(self.build)
        btns.addWidget(self.btn_build)
        self.btn_check = QPushButton("规范检查 check")
        self.btn_check.clicked.connect(self.check)
        btns.addWidget(self.btn_check)
        self.btn_preview = QPushButton("打开预览.html")
        self.btn_preview.clicked.connect(
            lambda: self._open_path(self.pack_dir / "预览.html" if self.pack_dir else None))
        btns.addWidget(self.btn_preview)
        self.btn_open_submit = QPushButton("打开投稿目录")
        self.btn_open_submit.clicked.connect(
            lambda: self._open_path(self.pack_dir / "submit" if self.pack_dir else None))
        btns.addWidget(self.btn_open_submit)
        self.btn_open_dir = QPushButton("打开项目目录")
        self.btn_open_dir.clicked.connect(lambda: self._open_path(self.pack_dir))
        btns.addWidget(self.btn_open_dir)
        btns.addStretch(1)
        v.addLayout(btns)

        self.check_list = QListWidget()
        self.check_list.setMaximumHeight(140)
        v.addWidget(self.check_list)

        self.preview_area = QScrollArea()
        self.preview_area.setWidgetResizable(True)
        self.preview_inner = QWidget()
        self.preview_layout = QGridLayout(self.preview_inner)
        self.preview_area.setWidget(self.preview_inner)
        v.addWidget(self.preview_area, 1)
        return w

    def build(self):
        if not self._require_ready():
            return
        self._run("合成中…", core.build_pack, self.sticker, self.pack_dir, step=3,
                  with_progress=True, progress_slot=self._on_build_progress,
                  on_done=self._on_build_done)

    def _on_build_progress(self, item, kind, msg):
        mark = {"ok": "✅", "skip": "⏭️"}.get(kind, "")
        self.check_list.addItem(QListWidgetItem(f"{mark} {item or ''} {msg}"))

    def _on_build_done(self, result):
        self.check_list.addItem(
            QListWidgetItem(f"✅ 合成完成：{len(result['gifs'])} 张 GIF，投稿目录 {result['submit']}"))
        self.rebuild_preview()
        self.refresh_cost()
        self._refresh_overview()

    def check(self):
        if not self._require_ready():
            return
        self._run("检查中…", core.check_pack, self.sticker, self.pack_dir, step=3,
                  on_done=self._on_check_done)

    def _on_check_done(self, result):
        self.last_fails = result["fails"]
        self.check_list.clear()
        for f in result["fails"]:
            it = QListWidgetItem(f"❌ FAIL  {f}")
            it.setForeground(QBrush(QColor("#c00000")))
            self.check_list.addItem(it)
        for wmsg in result["warns"]:
            it = QListWidgetItem(f"⚠️ WARN  {wmsg}")
            it.setForeground(QBrush(QColor("#b06000")))
            self.check_list.addItem(it)
        head = QListWidgetItem(
            f"结果：{len(result['fails'])} 个必须改（FAIL），{len(result['warns'])} 个要人看（WARN）。"
            "机器看不了的：错别字、变形、跳帧、权利是否清楚。")
        self.check_list.insertItem(0, head)
        self._refresh_overview()

    def rebuild_preview(self):
        # 清空旧内容
        self.movies = []
        while self.preview_layout.count():
            it = self.preview_layout.takeAt(0)
            wdg = it.widget()
            if wdg:
                wdg.deleteLater()
        if not self.pack_dir:
            return
        gifs = sorted((self.pack_dir / "submit" / "表情图").glob("*.gif"))
        pack = {}
        try:
            pack = core.load_pack_json(self.pack_dir)
        except Exception:
            pass
        col = row = 0
        for g in gifs:
            cell = QVBoxLayout()
            mov = QMovie(str(g))
            mov.setScaledSize(QSize(120, 120))
            lbl = QLabel()
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setMovie(mov)
            mov.start()
            self.movies.append(mov)
            cell.addWidget(lbl)
            i = int(g.stem)
            word = pack["stickers"][i - 1]["word"] if 0 < i <= len(pack.get("stickers", [])) else g.stem
            cap = QLabel(f"{i:02d} {word}")
            cap.setAlignment(Qt.AlignCenter)
            cell.addWidget(cap)
            holder = QWidget()
            holder.setLayout(cell)
            self.preview_layout.addWidget(holder, row, col)
            col += 1
            if col >= 6:
                col = 0
                row += 1
        # 素材缩略图
        assets = ["封面图.png", "聊天面板图标.png", "详情页横幅.png", "赞赏引导图.png", "赞赏致谢图.png"]
        found = [self.pack_dir / "submit" / a for a in assets if (self.pack_dir / "submit" / a).exists()]
        if found:
            row += 1
            title = QLabel("配套素材")
            title.setStyleSheet("font-weight: bold;")
            self.preview_layout.addWidget(title, row, 0, 1, 6)
            row += 1
            col = 0
            for f in found:
                cell = QVBoxLayout()
                lbl = QLabel()
                lbl.setAlignment(Qt.AlignCenter)
                pm = QPixmap(str(f))
                lbl.setPixmap(pm.scaled(140, 140, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                cell.addWidget(lbl)
                cap = QLabel(f.stem)
                cap.setAlignment(Qt.AlignCenter)
                cell.addWidget(cap)
                holder = QWidget()
                holder.setLayout(cell)
                self.preview_layout.addWidget(holder, row, col)
                col += 1
                if col >= 6:
                    col = 0
                    row += 1

    # ----- 项目管理 -----

    def new_project(self):
        name, ok = QInputDialog.getText(
            self, "新建项目", "项目名（同时是表情名，≤8 字、无标点空格）：")
        if not ok:
            return
        name = name.strip()
        if not name or len(name) > 8 or any(c in name for c in BAD_NAME_CHARS):
            QMessageBox.warning(self, "名字不合法", "要 1–8 字、无标点无空格。")
            return
        try:
            p = core.new_project(self.cfg, name)
        except OSError as e:
            QMessageBox.critical(self, "创建失败", str(e))
            return
        self.load_project(p)

    def open_project(self):
        start = str(self.cfg.get("packs_dir", ""))
        d = QFileDialog.getExistingDirectory(self, "选择项目目录（含 pack.json）", start)
        if not d:
            return
        if not (Path(d) / "pack.json").exists():
            QMessageBox.warning(self, "不是项目目录", f"{d}\n里没有 pack.json。请选项目目录，或先「新建项目」。")
            return
        self.load_project(Path(d))

    def _open_albums(self):
        AlbumDialog(self).exec()

    def _open_ideas(self):
        IdeasDialog(self).exec()

    def load_project(self, p):
        self.pack_dir = Path(p)
        rec = self.cfg.setdefault("recent_projects", [])
        s = str(self.pack_dir)
        if s in rec:
            rec.remove(s)
        rec.insert(0, s)
        del rec[8:]
        core.save_config(self.cfg)
        self._rebuild_recent_menu()
        try:
            pack = core.load_pack_json(self.pack_dir)
        except Exception as e:
            QMessageBox.critical(self, "读取失败", f"pack.json 解析失败：\n{e}")
            return
        self.apply_pack(pack)
        char = self.pack_dir / "character.png"
        if char.exists():
            pm = QPixmap(str(char))
            self.lbl_char_preview.setPixmap(
                pm.scaled(self.lbl_char_preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.char_status.setText("✅ 已有角色图。不满意可重新生成覆盖。")
        else:
            self.lbl_char_preview.setText("角色图预览")
            self.char_status.setText("还没生成角色图。")
        self.gen_log.setPlainText("")
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.lbl_plan.setText("还没预估")
        self.check_list.clear()
        self.rebuild_preview()
        self.lbl_proj.setText(f"项目：{self.pack_dir}")
        self.last_fails = []
        self.refresh_cost()
        self.goto_step(0)
        self._refresh_overview()

    def refresh_cost(self):
        if not self.pack_dir:
            self.lbl_cost.setText("")
            return
        usd = core.read_cost(self.sticker, self.pack_dir)
        self.lbl_cost.setText(f"累计花费 ${usd:.2f}" if usd else "尚未产生花费")

    # ----- 设置 / 帮助 -----

    def open_settings(self):
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec() == QDialog.Accepted:
            self.cfg = dlg.result_config()
            core.save_config(self.cfg)
            self._reload_sticker()

    def show_help(self):
        QMessageBox.information(
            self, "使用说明",
            "① 定角色：上传照片生成卡通角色图，这是整套形象的锚，不满意就重抽。\n\n"
            "② 写文案：名称 ≤8 字；含义词 ≤4 字不重复；动作写具体的身体动作；"
            "只换字不换动作会被判差异不足。\n\n"
            "③ 生成：先预估花费再开始；失败重跑只补缺的；某张不满意填序号重抽。\n"
            "没有 API Key 时点「查看出图提示词」去 ChatGPT 手动出图，存进对应目录。\n\n"
            "④ 合成与交付：合成后必须跑检查，FAIL 清零；再人工看错别字/变形/跳帧/白边。\n"
            "投稿素材在 submit/，上架文案照「上架文案.md」填，微信注册提交要本人实名操作。\n\n"
            "只做你有权使用的形象：不做明星、动漫游戏角色、二创同人；"
            "未成年人照片不投稿，仅可私下自用。")

    # ----- 通用 -----

    def _run(self, waiting, fn, *args, with_progress=False, progress_slot=None,
             on_done=None, on_fail=None, step=None):
        if self._worker_alive():
            QMessageBox.information(self, "请稍候", "有任务正在运行，等它结束再操作。")
            return
        self._busy_step = step
        self._busy_t0 = time.monotonic()
        self.statusBar().showMessage(waiting)
        self._refresh_overview()
        self.worker = Worker(fn, *args, with_progress=with_progress)
        if with_progress and progress_slot is not None:
            self.worker.progress.connect(progress_slot)
        self.worker.done.connect(
            lambda r: (self._finish_busy(), self.statusBar().clearMessage(),
                       on_done(r) if on_done else None))
        self.worker.failed.connect(
            lambda msg: (self._finish_busy(), self.statusBar().clearMessage(),
                         self._on_fail(msg, on_fail)))
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.finished.connect(self._on_worker_gone)
        self.worker.start()

    def _on_worker_gone(self):
        """线程真正结束时清引用，避免留僵尸（isRunning 对已删除对象会炸）。"""
        self.worker = None

    def _finish_busy(self):
        self._busy_step = None
        self._refresh_overview()

    def _on_fail(self, msg, custom):
        if custom:
            custom(msg)
        else:
            QMessageBox.critical(self, "出错了", msg)

    def _require_project(self):
        if not self.pack_dir:
            QMessageBox.information(self, "先建项目", "请先「文件 → 新建项目」或「打开项目」。")
            return False
        return True

    def _require_ready(self):
        if not self._require_project():
            return False
        if not (self.pack_dir / "pack.json").exists():
            QMessageBox.warning(self, "缺 pack.json", "当前目录不是有效项目目录。")
            return False
        return True

    def _open_path(self, path):
        if not path:
            QMessageBox.information(self, "先建项目", "请先打开一个项目。")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    apply_theme(app)
    app.setWindowIcon(theme.app_icon())  # 标题栏/任务栏图标，对话框自动继承
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
