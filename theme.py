# -*- coding: utf-8 -*-
"""全局主题：暖白底 + 珊瑚橙主色的卡片式风格（Fusion 之上套 QSS）。

配色原则：主色珊瑚橙只给「当前页主操作按钮」和进度/选中态，避免满屏开花；
日志/生成输出用深色控制台区分「内容区 vs 操作区」。任何厂商/平台都不依赖，
字体按 微软雅黑 → 苹方 → Segoe UI 依次回落。

QSS 的 url() 不支持 data-URL，相对路径又随 cwd 漂移——所以下拉/微调箭头
用运行时生成的小 PNG（存数据目录 .theme/ 下），QSS 里引绝对路径。
"""
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QPointF
from PySide6.QtGui import (
    QBrush, QColor, QIcon, QImage, QLinearGradient, QPainter, QPen,
    QPixmap, QPolygonF,
)
from PySide6.QtWidgets import QApplication

import core

ACCENT = "#F2653A"          # 珊瑚橙（主操作）
ACCENT_DARK = "#D9502A"
PAGE_BG = "#F5F3EE"         # 暖白页面底
CARD_BG = "#FFFFFF"
CARD_BORDER = "#E5E0D8"
TEXT = "#3A362F"
TEXT_MUTED = "#6B655B"
ARROW_COLOR = QColor("#8D877D")

_THEME_DIR = Path(core.PROJECT_ROOT) / ".theme"


def _arrow_png(path, direction):
    """画一个小三角箭头 PNG（QSS 的 CSS 三角技巧渲染不可靠，用图最稳）。"""
    img = QImage(12, 12, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(ARROW_COLOR)
    if direction == "down":
        pts = [QPointF(2.5, 4.5), QPointF(9.5, 4.5), QPointF(6, 9)]
    else:  # up
        pts = [QPointF(2.5, 7.5), QPointF(9.5, 7.5), QPointF(6, 3)]
    p.drawPolygon(QPolygonF(pts))
    p.end()
    img.save(str(path))


def _ensure_arrows():
    _THEME_DIR.mkdir(parents=True, exist_ok=True)
    down, up = _THEME_DIR / "arrow-down.png", _THEME_DIR / "arrow-up.png"
    if not down.exists():
        _arrow_png(down, "down")
    if not up.exists():
        _arrow_png(up, "up")
    return down.as_posix(), up.as_posix()


def build_qss():
    arrow_down, arrow_up = _ensure_arrows()
    return f"""
* {{
    font-family: "Microsoft YaHei UI", "PingFang SC", "Segoe UI", sans-serif;
    font-size: 13px;
    color: {TEXT};
}}
QMainWindow, QDialog {{ background: {PAGE_BG}; }}

/* ---- 菜单 ---- */
QMenuBar {{ background: transparent; padding: 2px 6px; }}
QMenuBar::item {{ padding: 5px 10px; border-radius: 6px; }}
QMenuBar::item:selected {{ background: #ECE7DE; }}
QMenu {{ background: {CARD_BG}; border: 1px solid {CARD_BORDER}; padding: 5px; }}
QMenu::item {{ padding: 7px 26px 7px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: #FDEDE7; color: #B03D18; }}
QMenu::separator {{ height: 1px; background: {CARD_BORDER}; margin: 5px 8px; }}

/* ---- 卡片（GroupBox）---- */
QGroupBox {{
    background: {CARD_BG};
    border: 1px solid {CARD_BORDER};
    border-radius: 10px;
    margin-top: 12px;
    padding: 10px 12px 12px 12px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    top: 1px;
    padding: 0 5px;
    background: {PAGE_BG};
    color: {TEXT_MUTED};
    font-weight: 600;
}}

/* ---- 输入控件 ---- */
QLineEdit, QComboBox, QSpinBox, QTextEdit, QPlainTextEdit {{
    background: {CARD_BG};
    border: 1px solid #D9D3C9;
    border-radius: 8px;
    padding: 5px 8px;
    selection-background-color: {ACCENT};
    selection-color: #FFFFFF;
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover {{ border-color: #C0B9AC; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {ACCENT};
}}
QLineEdit[readOnly="true"] {{ background: #F7F4EE; color: {TEXT_MUTED}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
    background: #F1EEE8; color: #A9A396;
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url({arrow_down}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background: {CARD_BG};
    border: 1px solid {CARD_BORDER};
    border-radius: 8px;
    padding: 4px;
    outline: none;
    selection-background-color: #FDEDE7;
    selection-color: {TEXT};
}}
QSpinBox::up-button {{ subcontrol-origin: padding; subcontrol-position: top right; width: 18px; border: none; background: transparent; }}
QSpinBox::down-button {{ subcontrol-origin: padding; subcontrol-position: bottom right; width: 18px; border: none; background: transparent; }}
QSpinBox::up-arrow {{ image: url({arrow_up}); width: 12px; height: 12px; }}
QSpinBox::down-arrow {{ image: url({arrow_down}); width: 12px; height: 12px; }}

/* ---- 按钮 ---- */
QPushButton {{
    background: {CARD_BG};
    border: 1px solid #D9D3C9;
    border-radius: 8px;
    padding: 6px 14px;
}}
QPushButton:hover {{ background: #F8F5EF; border-color: #C0B9AC; }}
QPushButton:pressed {{ background: #EFEAE0; }}
QPushButton:disabled {{ color: #B3ADA1; background: #F4F1EA; border-color: {CARD_BORDER}; }}
QPushButton[primary="true"] {{
    background: {ACCENT};
    border: 1px solid {ACCENT_DARK};
    color: #FFFFFF;
    font-weight: 600;
}}
QPushButton[primary="true"]:hover {{ background: #E05530; }}
QPushButton[primary="true"]:pressed {{ background: #C94820; }}
QPushButton[primary="true"]:disabled {{
    background: #F5B9A6; border-color: #F5B9A6; color: #FDF3EF;
}}

/* ---- 复选框 ---- */
QCheckBox {{ spacing: 6px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid #C0B9AC;
    border-radius: 4px;
    background: {CARD_BG};
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT_DARK}; }}

/* ---- 列表 ---- */
QListWidget {{
    background: {CARD_BG};
    border: 1px solid {CARD_BORDER};
    border-radius: 10px;
    padding: 4px;
    outline: none;
}}
QListWidget::item {{ border-radius: 6px; margin: 1px 2px; }}
QListWidget::item:hover {{ background: #F6F1EA; }}
QListWidget::item:selected {{ background: #FDEDE7; color: #B03D18; }}

/* ---- 表格 ---- */
QTableWidget {{
    background: {CARD_BG};
    alternate-background-color: #FBFAF6;
    border: 1px solid {CARD_BORDER};
    border-radius: 10px;
    gridline-color: #F0EBE3;
    selection-background-color: #FDEDE7;
    selection-color: {TEXT};
    outline: none;
}}
QTableWidget::item {{ padding: 4px 6px; }}
QHeaderView::section {{
    background: #F7F4EE;
    border: none;
    border-bottom: 1px solid {CARD_BORDER};
    padding: 6px 8px;
    font-weight: 600;
    color: {TEXT_MUTED};
}}

/* ---- 进度条 ---- */
QProgressBar {{
    background: #ECE7DE;
    border: none;
    border-radius: 7px;
    min-height: 14px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 7px; }}

/* ---- 滚动区与滚动条 ---- */
QScrollArea {{ background: {CARD_BG}; border: 1px solid {CARD_BORDER}; border-radius: 10px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #D5CFC4; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #BDB6A9; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #D5CFC4; border-radius: 4px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: #BDB6A9; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---- 深色控制台：生成日志 / API 调用日志 ---- */
QPlainTextEdit#consoleLog, QPlainTextEdit#apiLog {{
    background: #2F2C33;
    color: #DDD8D0;
    border: none;
    border-radius: 10px;
    padding: 8px;
    font-family: "Consolas", "Menlo", monospace;
    font-size: 12px;
    selection-background-color: #4A4450;
    selection-color: #FFFFFF;
}}

/* ---- 状态栏 / 提示 ---- */
QStatusBar {{ background: transparent; color: {TEXT_MUTED}; border-top: 1px solid {CARD_BORDER}; }}
QStatusBar QLabel {{ color: {TEXT_MUTED}; }}
QToolTip {{
    background: #3A362F;
    color: {PAGE_BG};
    border: none;
    padding: 6px 8px;
    border-radius: 6px;
}}
"""


def apply_theme(app: QApplication):
    app.setStyleSheet(build_qss())


# ---------- 应用图标（窗口左上角 / 任务栏 / 打包 exe）----------
#
# 纯 QPainter 矢量绘制：珊瑚橙渐变圆角底 + 白色对话气泡 + 笑脸 + 四角星。
# 仓库不放二进制素材，三平台渲染一致；打包时由 build_exe.py 渲染成 ico/icns。

_icon_cache = None


def _draw_icon(size=256):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 256.0

    # 底：珊瑚橙对角渐变圆角方块
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0.0, QColor("#FF8A5C"))
    grad.setColorAt(1.0, QColor("#E85530"))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(grad))
    p.drawRoundedRect(QRectF(0, 0, size, size), 58 * s, 58 * s)

    # 白色对话气泡 + 左下尾巴
    p.setBrush(QColor("#FFFFFF"))
    p.drawRoundedRect(QRectF(44 * s, 58 * s, 168 * s, 122 * s), 38 * s, 38 * s)
    p.drawPolygon(QPolygonF([
        QPointF(82 * s, 172 * s), QPointF(130 * s, 172 * s), QPointF(94 * s, 212 * s)]))

    # 笑脸：圆角竖条眼睛 + 微笑弧线 + 腮红
    p.setBrush(QColor("#3A362F"))
    p.drawRoundedRect(QRectF(88 * s, 92 * s, 15 * s, 30 * s), 7.5 * s, 7.5 * s)
    p.drawRoundedRect(QRectF(153 * s, 92 * s, 15 * s, 30 * s), 7.5 * s, 7.5 * s)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(QColor("#3A362F"), 10 * s, Qt.SolidLine, Qt.RoundCap))
    p.drawArc(QRectF(96 * s, 108 * s, 64 * s, 56 * s), 200 * 16, 140 * 16)
    p.setPen(Qt.NoPen)
    blush = QColor(255, 122, 90, 80)
    p.setBrush(blush)
    p.drawEllipse(QRectF(64 * s, 126 * s, 24 * s, 14 * s))
    p.drawEllipse(QRectF(168 * s, 126 * s, 24 * s, 14 * s))

    # 右上角黄色四角星（点缀）
    p.setBrush(QColor("#FFD66B"))
    cx, cy, r, k = 214 * s, 46 * s, 18 * s, 0.28 * 18 * s
    p.drawPolygon(QPolygonF([
        QPointF(cx, cy - r), QPointF(cx + k, cy - k), QPointF(cx + r, cy),
        QPointF(cx + k, cy + k), QPointF(cx, cy + r), QPointF(cx - k, cy + k),
        QPointF(cx - r, cy), QPointF(cx - k, cy - k)]))
    p.end()
    return pm


def app_icon():
    """QIcon，覆盖 16–256 各标准尺寸（小尺寸从 256 主渲染平滑缩放）。"""
    global _icon_cache
    if _icon_cache is None:
        master = _draw_icon(256)
        icon = QIcon()
        for sz in (256, 128, 64, 48, 32, 24, 16):
            icon.addPixmap(master.scaled(sz, sz, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        _icon_cache = icon
    return _icon_cache
