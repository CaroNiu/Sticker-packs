# -*- coding: utf-8 -*-
"""回归测试：gen_pack 必须自己注入 env_patch，否则分发器走原版接口 → 静默无日志。

背景（2026-11-09 线上 bug）：make_character 包了 env_patch 而 gen_pack 漏了，
第③步点开始生成后永远停在“提交中”、API 日志面板全空。
本测试在“环境变量干净”的前提下跑 gen_pack：
  1) 正常路径：mock 方舟服务收 9 张请求，产出 9 张精灵图，api_log 出现“▶ 图片生成”；
  2) 缺 key 路径：每张显式 fail 进 progress（SystemExit 被接住），绝不静默。
"""
import json
import os
import shutil
import sys
import threading
import base64
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))
import core  # noqa: E402

# --- 环境必须干净：GUI 进程里 OPENAI_* 未设置，这正是 bug 的触发条件 ---
for k in ("OPENAI_API_KEY", "OPENAI_BASE_URL"):
    os.environ.pop(k, None)
assert not os.environ.get("OPENAI_BASE_URL"), "前置条件失败：OPENAI_BASE_URL 已被外部设置"
# 127.0.0.1 的 mock 不能走代理：Windows 上 urllib 读注册表系统代理，env 的 no_proxy
# 对它无效，必须直接装一个无代理 opener（urlopen 全局生效，且要在任何请求发出前装）
for k in ("no_proxy", "NO_PROXY"):
    os.environ[k] = "127.0.0.1,localhost"
import urllib.request as _ur  # noqa: E402
_ur.install_opener(_ur.build_opener(_ur.ProxyHandler({})))

# --- mock 方舟：POST /images/generations → 一张 64x64 PNG 的 b64 ---
from PIL import Image as _PILImage  # noqa: E402

_buf = io.BytesIO()
_PILImage.new("RGB", (64, 64), (240, 240, 240)).save(_buf, format="PNG")
TINY_PNG_B64 = base64.b64encode(_buf.getvalue()).decode()

hits = []
lock = threading.Lock()


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        with lock:
            hits.append(self.path)
        body = json.dumps({
            "created": 0,
            "data": [{"b64_json": TINY_PNG_B64}],
            "usage": {"input_tokens": 10, "output_tokens": 40,
                      "input_tokens_details": {"image_tokens": 300, "text_tokens": 10}},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # 静默 mock 自身的访问日志
        pass


srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

# --- 日志收集 ---
api_lines, api_lock = [], threading.Lock()


def _collect(ln):
    with api_lock:
        api_lines.append(ln)


core.add_log_listener(_collect)

# --- 用真实项目的 pack.json + character.png 建临时包 ---
real_pack = Path(core.DEFAULT_CONFIG.get("packs_dir", "packs")) / "测试猫"
if not (real_pack / "pack.json").exists():
    # 找不到真实项目就合成最小包，测试不依赖具体项目
    real_pack = None
tmp = Path(__file__).parent / "_tmp_genpack"
if tmp.exists():
    shutil.rmtree(tmp)
tmp.mkdir()
if real_pack:
    shutil.copy2(real_pack / "pack.json", tmp / "pack.json")
    shutil.copy2(real_pack / "character.png", tmp / "character.png")
else:
    (tmp / "character.png").write_bytes(_buf.getvalue())
    (tmp / "pack.json").write_text(json.dumps({
        "name": "测试喵", "intro": "测试", "reward_line": "谢谢观看",
        "copyright": "", "frame_ms": 120,
        "stickers": [{"word": "你好", "action": "waving hello"} for _ in range(2)],
    }, ensure_ascii=False), encoding="utf-8")

cfg = {**core.DEFAULT_CONFIG,
       # 分发器按 base_url 含 "volces.com" 判定走方舟，mock 用路径段模拟这个特征
       "api_key": "ark-mock-key", "base_url": f"http://127.0.0.1:{port}/volces.com-mock/api/plan/v3",
       "gen_model": "mock-seedream", "character_model": "mock-seedream",
       "jobs": 2, "quality": "medium"}

sticker = core.load_sticker(cfg["skill_dir"])
progress_events = []
r = core.gen_pack(sticker, cfg, tmp, with_assets=False, redo=None,
                  progress=lambda item, kind, msg: progress_events.append((item, kind, msg)))

n_stickers = len(json.loads((tmp / "pack.json").read_text(encoding="utf-8"))["stickers"])
fails = [e for e in progress_events if e[1] == "fail"]
oks = [e for e in progress_events if e[1] == "ok"]
assert r["errors"] == [], f"正常路径不应有失败：{r['errors'][:3]}"
assert r["total"] == n_stickers, f"total={r['total']} 应为 {n_stickers}"
assert len(oks) == n_stickers, f"ok 事件 {len(oks)} != {n_stickers}"
assert not fails, f"正常路径不应有 fail 事件：{fails[:3]}"
assert (tmp / "sheets" / "01.png").exists(), "sheets/01.png 未产出"
assert (tmp / "costs.jsonl").exists(), "costs.jsonl 未写"
with lock:
    assert len(hits) == n_stickers, f"mock 收到 {len(hits)} 次请求，应为 {n_stickers}"
with api_lock:
    ark_lines = [ln for ln in api_lines if "▶ 图片生成" in ln]
    assert ark_lines, f"api_log 未出现“▶ 图片生成”（走了原版接口？）：{api_lines[:5]}"
    assert len(ark_lines) == n_stickers, f"▶ 行数 {len(ark_lines)} != {n_stickers}"
print(f"PASS 1 正常路径：{n_stickers} 张全走方舟 mock，日志 {len(ark_lines)} 条 ▶，env 未手动注入")

# --- 反例：缺 key → 每张显式 fail，不静默、不挂起 ---
shutil.rmtree(tmp / "sheets", ignore_errors=True)  # 清掉第一轮产物，让 todo 重新非空
cfg_nok = {**cfg, "api_key": ""}
progress2 = []
r2 = core.gen_pack(sticker, cfg_nok, tmp, with_assets=False, redo=None,
                   progress=lambda item, kind, msg: progress2.append((item, kind, msg)))
fails2 = [e for e in progress2 if e[1] == "fail"]
assert r2["errors"] and len(fails2) == r2["total"], f"缺 key 应每张显式 fail：{r2['errors'][:2]} / {len(fails2)}"
assert any("OPENAI_API_KEY" in e[2] or "key" in e[2].lower() for e in fails2), f"fail 详情没带原因：{fails2[:2]}"
print(f"PASS 2 缺 key 路径：{len(fails2)}/{r2['total']} 张显式 fail 且带原因，无静默")

srv.shutdown()
shutil.rmtree(tmp, ignore_errors=True)
print("API GEN-ENV PASS")
