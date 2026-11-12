# -*- coding: utf-8 -*-
"""表情包工坊 GUI 核心封装。

复用 ray-sticker-shop skill 的 scripts/sticker.py 流水线（提示词、GIF 压缩、
微信规范检查全部来自 skill 本体，不复制逻辑），只做编排：进度回调、
环境变量注入、结果结构化。
"""
import argparse
import base64
import contextlib
import concurrent.futures as cf
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent
# 打包成 exe 后，__file__ 指向临时解压目录（一次性），配置/作品必须放 exe 旁边才持久
FROZEN = getattr(sys, "frozen", False)
if FROZEN:
    exe_dir = Path(sys.executable).resolve().parent
    if sys.platform == "darwin" and ".app" in exe_dir.parts:
        # Mac .app：bundle 内部不可写（Gatekeeper/只读介质），数据放用户目录（macOS 惯例）
        PROJECT_ROOT = Path.home() / "Library" / "Application Support" / "StickerWorkshop"
        PROJECT_ROOT.mkdir(parents=True, exist_ok=True)
    else:
        PROJECT_ROOT = exe_dir
CONFIG_PATH = PROJECT_ROOT / "config.json"
DEFAULT_SKILL_DIR = Path.home() / ".claude" / "skills" / "ray-sticker-shop" / "scripts"
# 打包内置的 skill 副本（build_exe.py 复制进 vendor/，随 exe 分发）
BUNDLED_SKILL = Path(getattr(sys, "_MEIPASS", "") or PROJECT_ROOT) / "vendor" / "sticker.py"

# ---------- API 调用日志（线程安全，GUI 订阅显示）----------

import collections
import threading

_api_log_buf = collections.deque(maxlen=800)
_api_log_lock = threading.Lock()
_api_log_listeners = []
_api_log_total = 0   # 历史总行数（deque 会环绕，用总行数精确对位）


def api_log(msg):
    global _api_log_total
    line = time.strftime("[%H:%M:%S] ") + msg
    with _api_log_lock:
        _api_log_buf.append(line)
        _api_log_total += 1
    for cb in list(_api_log_listeners):
        try:
            cb(line)
        except Exception:
            pass


def add_log_listener(cb):
    _api_log_listeners.append(cb)


def get_api_log():
    """返回 (日志行列表, 历史总行数)；列表可能只含最近 800 行。"""
    with _api_log_lock:
        return list(_api_log_buf), _api_log_total

DEFAULT_CONFIG = {
    "api_key": "",
    "base_url": "",
    "skill_dir": str(DEFAULT_SKILL_DIR),
    "packs_dir": str(PROJECT_ROOT / "packs"),
    "gen_model": "gpt-image-1",
    "character_model": "gpt-image-1",
    "quality": "medium",
    "text_api_key": "",
    "text_base_url": "",
    "text_model": "gpt-4o-mini",
    "jobs": 4,
    "style": "meme-style cartoon, oversized expressive head, tiny simple body, thick clean outlines, flat colors, smug cheeky default face",
    "frame_ms": 120,
    "background": "transparent",
    "recent_projects": [],
}

BANNED = ["微信", "wechat", "腾讯", "官方", "认证", "正版"]

# 开源通用化：接口地址留空一律回落 OpenAI 官方（任何 OpenAI 兼容服务填地址即可覆盖）
OPENAI_DEFAULT_BASE = "https://api.openai.com/v1"

# 新项目默认 8 张（无 Key 手动模式的开箱模板）：功能位保留，态度换血——
# 熊猫头式万能回复/情绪爆发/认怂摆烂，动作演到夸张
DEFAULT_STICKERS = [
    {"word": "已阅", "caption": "已阅", "action": "flicks one paw as if stamping a document, then slides the invisible paper away without looking up"},
    {"word": "行吧", "caption": "行吧", "action": "shrugs with both palms up, then waves one hand dismissively while rolling the eyes upward"},
    {"word": "等会", "caption": "等会", "action": "holds up one finger without lifting the head, then slowly points at an imaginary watch with a flat stare"},
    {"word": "笑死", "caption": "笑死", "action": "slaps the floor laughing with legs kicking in the air, wipes a tear, then points at the viewer while gasping"},
    {"word": "就这", "caption": "就这？", "action": "leans back with a slow eye-roll up to the ceiling, then tilts the head with a smug half-smirk"},
    {"word": "下次一定", "caption": "下次一定", "action": "bows politely with hands together, then immediately turns away and sneaks off tiptoeing"},
    {"word": "躺了", "caption": "躺了", "action": "melts backward into a boneless puddle on the floor, one arm draped over the face, tail flopping last"},
    {"word": "再说", "caption": "再说", "action": "turns the head away with a big slow blink, then waves one paw backward over the shoulder while walking off"},
]

ASSET_SPECS = [
    ("cover", (240, 240), "封面图.png", 500, True),
    ("icon", (50, 50), "聊天面板图标.png", 100, True),
    ("banner", (750, 400), "详情页横幅.png", 500, False),
    ("reward_guide", (750, 560), "赞赏引导图.png", 500, False),
    ("reward_thanks", (750, 750), "赞赏致谢图.png", 500, False),
]


# ---------- 配置 ----------

def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    else:
        save_config(cfg)  # 首次运行落盘模板（exe 场景：用户直接编辑 exe 旁的 config.json 填 key）
    # 相对 packs_dir 锚定到数据目录：Mac 双击 .app 时 cwd 是 "/"，相对路径会写到根目录炸权限
    pd = Path(cfg.get("packs_dir") or "packs")
    if not pd.is_absolute():
        cfg["packs_dir"] = str(PROJECT_ROOT / pd)
    return cfg


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- skill 加载 ----------

def _is_ark_base(base_url):
    """base_url 是否指向火山方舟（唯一已知需要 JSON 协议适配的服务），其余全走 OpenAI 兼容链路。"""
    return "volces.com" in (base_url or "")


def load_sticker(skill_dir):
    f = Path(skill_dir) / "sticker.py"
    if not f.exists() and BUNDLED_SKILL.exists():
        f = BUNDLED_SKILL  # 独立运行包：目标机器没装 skill 时用内置副本兜底
    if not f.exists():
        raise FileNotFoundError(
            f"找不到 skill 脚本：{f}\n"
            "请先 git clone https://github.com/imraywang/ray-sticker-shop "
            "~/.claude/skills/ray-sticker-shop，或在「设置」里指定脚本目录。"
        )
    spec = importlib.util.spec_from_file_location("sticker_shop_pipeline", str(f))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)

    # Windows 兼容补丁：skill 的 load_pack 用默认编码 read_text()，中文 Windows
    # 默认 GBK，读 UTF-8 的 pack.json（含中文）会 UnicodeDecodeError。
    # 不改 skill 源文件（避免 git pull 冲突），运行时覆盖为显式 UTF-8。
    def _load_pack_utf8(pack_dir, _mod=mod):
        p = Path(pack_dir)
        pack = json.loads((p / "pack.json").read_text(encoding="utf-8"))
        return p, pack

    mod.load_pack = _load_pack_utf8

    # 图片接口分发：唯一已知需要协议适配的是火山方舟（volces.com，JSON 接口），
    # 其余一律走 OpenAI 兼容 multipart /images/edits——OpenAI 官方、中转聚合网关、
    # 本地推理服务等通用。按调用时的环境变量分发，不改 skill 源文件。
    mod._edit_openai_compat = mod._edit  # 原版实现挂回模块，便于测试替换与排查

    def _edit_dispatch(image_path, prompt, size, background, model, quality, log_path):
        if _is_ark_base(os.environ.get("OPENAI_BASE_URL", "")):
            return _edit_ark(image_path, prompt, size, background, model, log_path)
        # 走 OpenAI 兼容接口时明确记一条日志：这条路没有埋点、长超时，
        # 出问题极易表现为“静默无日志”
        api_log("→ 图片路由：OpenAI 兼容 multipart 接口（/images/edits）")
        return mod._edit_openai_compat(image_path, prompt, size, background, model, quality, log_path)

    mod._edit = _edit_dispatch
    return mod


@contextlib.contextmanager
def env_patch(cfg):
    """把 GUI 设置里的 API 配置注入 os.environ，调用完恢复。"""
    keys = ("OPENAI_API_KEY", "OPENAI_BASE_URL")
    old = {k: os.environ.get(k) for k in keys}
    if cfg.get("api_key"):
        os.environ["OPENAI_API_KEY"] = cfg["api_key"]
    if cfg.get("base_url"):
        os.environ["OPENAI_BASE_URL"] = cfg["base_url"]
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _make_transparent(raw, tol=30):
    """方舟模型输出 RGB 无透明通道，把「要求透明底」的图从四边洪泛填充抠出透明区。"""
    from PIL import Image
    from collections import deque
    im = Image.open(io.BytesIO(raw)).convert("RGBA")
    w, h = im.size
    px = im.load()
    corners = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]
    if any(c[3] == 0 for c in corners):
        return raw  # 已有透明通道，直接用
    bgs = []
    for c in corners:
        if not any(abs(c[0] - b[0]) <= 12 and abs(c[1] - b[1]) <= 12 and abs(c[2] - b[2]) <= 12 for b in bgs):
            bgs.append(c)

    def near(c):
        return any(abs(c[0] - b[0]) <= tol and abs(c[1] - b[1]) <= tol and abs(c[2] - b[2]) <= tol for b in bgs)

    api_log("✂ 开始抠透明底（洪泛填充）…")
    _t0 = time.time()

    seen = bytearray(w * h)
    q = deque()
    for x in range(w):
        q += [(x, 0), (x, h - 1)]
    for y in range(h):
        q += [(0, y), (w - 1, y)]
    while q:
        x, y = q.pop()
        if x < 0 or y < 0 or x >= w or y >= h or seen[y * w + x]:
            continue
        c = px[x, y]
        if not near(c):
            continue
        seen[y * w + x] = 1
        px[x, y] = (c[0], c[1], c[2], 0)
        q += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
    buf = io.BytesIO()
    im.save(buf, "PNG")
    api_log(f"✂ 透明底完成，耗时 {time.time() - _t0:.1f}s")
    return buf.getvalue()


def _edit_ark(image_path, prompt, size, background, model, log_path):
    """火山方舟（volces.com）图片接口适配，返回图片字节（契约同 skill 原版 _edit）。

    方舟不走 OpenAI 的 multipart /images/edits，而是 JSON POST
    {base}/images/generations，参考图以 data-URL 数组传入。
    base_url 原样使用：Coding 套餐入口（…/api/plan/v3）与标准入口（…/api/v3）
    都能出图，不要改写用户的地址。
    """
    base = os.environ.get("OPENAI_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
    base = re.sub(r"/images/generations$", "", base)  # 容错：把完整接口地址粘进 base_url 也能用
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        sys.exit("缺 OPENAI_API_KEY。没有 key 时用 prompts 命令拿提示词，到 ChatGPT 或 Codex 里出图，再跑 build。")
    # MIME 必须和图片真实格式一致，写错（如 JPEG 标成 png）方舟会 500
    fmt = {"PNG": "png", "JPEG": "jpeg", "WEBP": "webp", "BMP": "bmp"}.get(Image.open(image_path).format, "png")
    b64img = base64.b64encode(Path(image_path).read_bytes()).decode()
    body = {
        "model": model,
        "prompt": prompt,
        "image": [f"data:image/{fmt};base64,{b64img}"],
        "response_format": "b64_json",
        "watermark": False,  # 默认 true 会加「AI生成」角标，投稿素材不能带
    }
    if "seededit" not in model.lower():
        # seededit（i2i 编辑）不支持 size；seedream 系给显式 2048x2048：
        # 5.0 系要求总像素 ≥2560x1440，skill 里的 960/1024 会被拒，2K 档各方舟模型通用，
        # build 环节本来就会切格/缩放，不影响产物。
        body["size"] = "2048x2048"
    if "seedream-5" in model.lower():
        body["output_format"] = "png"  # 5.x 支持；4.x 无此字段
    req = urllib.request.Request(
        f"{base}/images/generations",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    for attempt in range(4):
        api_log(f"▶ 图片生成 model={model} size={body.get('size', '(自动)')} "
                f"参考图={Path(image_path).name} 尝试 {attempt + 1}/4（一般 60–120 秒）")
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.load(r)
            api_log(f"✅ 服务端响应 OK，耗时 {time.time() - t0:.0f}s")
            break
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:400]
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                api_log(f"⚠ HTTP {e.code} → {5 * (attempt + 1)}s 后重试")
                time.sleep(5 * (attempt + 1))
                continue
            hint = ""
            if e.code == 401 and key.startswith("ark-") and "plan" not in base:
                hint = ("（ark- 开头的是 Coding 套餐 key，标准入口 /api/v3 不认；"
                        "base_url 请填 https://ark.cn-beijing.volces.com/api/plan/v3）")
            elif "agent plan" in msg.lower():
                hint = "（当前入口/套餐不包含该图片生成模型）"
            api_log(f"❌ HTTP {e.code}，放弃本次")
            raise RuntimeError(f"HTTP {e.code}: {msg}{hint}") from None
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == 3:
                api_log("❌ 网络失败，放弃本次")
                raise RuntimeError(str(e)) from None
            api_log(f"⚠ 网络异常（{type(e).__name__}）→ {5 * (attempt + 1)}s 后重试")
            time.sleep(5 * (attempt + 1))
    d = (data.get("data") or [{}])[0]
    if d.get("error"):
        err = d["error"]
        raise RuntimeError(f"方舟生成失败：{err.get('code')} {err.get('message')}")
    u = data.get("usage") or {}
    # 方舟按张计费（模型×分辨率定价），与 OpenAI token 计费不同，无法折算美元，按 0 记，
    # 实际花费以火山引擎控制台账单为准。
    with open(log_path, "a") as f:
        f.write(json.dumps({"size": body.get("size", "auto"), "usage": {"provider": "ark", **u}, "usd": 0.0}) + "\n")
    if d.get("b64_json"):
        raw = base64.b64decode(d["b64_json"])
    else:
        with urllib.request.urlopen(d["url"], timeout=120) as r:  # 兜底：返回 url（24h 有效）就当场下载
            raw = r.read()
    api_log(f"📷 收到图片 {len(raw) // 1024}KB（{model}）")
    if background == "transparent":
        raw = _make_transparent(raw)
    return raw


def test_connection(cfg):
    """设置页「测试连接」：只探测网络与鉴权，不产生费用。"""
    base = (cfg.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    base = re.sub(r"/images/generations$", "", base)  # 容错：粘成完整接口地址时剥掉
    req = urllib.request.Request(
        f"{base}/models",
        headers={"Authorization": f"Bearer {cfg.get('api_key')}"} if cfg.get("api_key") else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return f"✅ 连接正常（HTTP {r.status}）"
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return "⚠ 网络已通，但鉴权失败（HTTP %d）：检查 API Key" % e.code
        if e.code == 404:
            return "⚠ 网络可达；该地址无 /models 探针（方舟 plan 入口属正常），请直接生成实测"
        return f"✅ 网络可达（HTTP {e.code}）"
    except Exception as e:
        return f"❌ 连接失败：{type(e).__name__}: {e}"


# ---------- 文案模型（对话补全）----------

COPY_SYSTEM = """你是微信表情开放平台的资深表情包策划师。效率要求：判断要快、给结果要直接——不要长篇推理、不要解释设计思路，直接输出 JSON，你的思考时间用户等不起。
设计逻辑对标熊猫头、金馆长这类国民级表情包：
每一张都是一次社交动作（怼人/认怂/阴阳），收到的人能在下一句话里直接把它扔出去。
角色基准脸自带态度（谜之自信/无赖感），整套文案必须延续这个底色——
温和礼貌、滴水不漏的表达等于失败；老老实实的「收到/好的/谢谢/加油/哈哈哈」原样出现等于失败。
硬性规范（违反会被平台驳回，必须遵守）：
- name：表情名称，1-8 个汉字，无标点无空格，不能含"微信/wechat/腾讯/官方/认证/正版"
- intro：表情介绍，不超过 80 字，讲角色性格或小情景，不能含上述违禁词
- reward_line：赞赏引导语，5-15 字，与表情强相关
- stickers：8-12 张。每张：
  - word：含义词，不超过 4 个汉字，彼此不重复，不带任何标点符号（平台要求）。
    要口语化、能直接当回击用：爱答不理的「嗯」「行吧」「已阅」好过老实的「收到」「好的」；
    禁用首批蹦出的常规词原样（收到/好的/稍等/谢谢/不客气/加油/晚安/抱抱），用带态度的变体替代
  - caption：配字（默认与 word 相同，可加口语化语气字，同样不带违禁词）
  - action：动作用英文写，必须是一套连贯具体的身体动作（2-3 个动作串联），
    把情绪演到夸张——拍桌、翻白眼、瘫成一滩、扣手机像盖章、笑到捶地，
    不要抽象形容词（不要 cute/happy 这种），动作要能体现该含义词的态度
- 选题覆盖（功能位保留，态度换血）：3 张万能回复（敷衍/爱答不理式，别老实回复）
  + 2 张情绪爆发（演到夸张失真）+ 2 张社交武器（怼人/阴阳，玩笑级不带脏）
  + 1-2 张认怂/摆烂（理不直气也壮的无赖感）
只输出纯 JSON，不要 markdown 代码围栏，不要任何解释文字，格式：
{"name":"...","intro":"...","reward_line":"...","stickers":[{"word":"...","caption":"...","action":"..."}]}"""


def _chat_once(base, key, model, system, user, max_tokens, timeout):
    """OpenAI 风格对话补全（方舟套餐入口与标准入口、OpenAI 兼容网关都支持）。"""
    base = re.sub(r"/images/generations$", "", base.rstrip("/"))  # 容错：粘成完整接口地址时剥掉
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    api_log(f"▶ 文案请求 model={model} 地址={base}/chat/completions")
    _ct0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    api_log(f"💬 文案模型 {model} 响应 OK，耗时 {time.time() - _ct0:.1f}s")
    if data.get("error"):
        raise RuntimeError(f"文案模型返回错误：{data['error'].get('message', data['error'])}")
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    return msg.get("content") or msg.get("reasoning_content") or ""


def _chat(base, key, model, system, user, max_tokens=3000, timeout=180, net_retries=3):
    """对话补全 + 有限重试。

    HTTP 429/5xx 重试 3 次（服务端限流/抖动，重试通常有效）；
    网络超时/连接错误重试 net_retries 次（超时大概率是模型太慢或网络挂，
    盲目重试只会拖长等待，所以创意这类快任务传 net_retries=1）。
    每次重试都打日志——静默重试会让用户以为程序卡死。
    """
    last = None
    for attempt in range(4):
        check_cancel("等待文案请求")
        try:
            result = _chat_once(base, key, model, system, user, max_tokens, timeout)
            check_cancel("文案请求已返回，结果作废")
            return result
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:300]
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                api_log(f"⚠ 文案请求 HTTP {e.code} → {5 * (attempt + 1)}s 后重试")
                time.sleep(5 * (attempt + 1))
                last = RuntimeError(f"HTTP {e.code}: {msg}")
                continue
            hint = "（鉴权失败：检查文案模型的 API Key）" if e.code in (401, 403) else ""
            raise RuntimeError(f"HTTP {e.code}: {msg}{hint}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt >= net_retries:
                raise RuntimeError(
                    f"文案请求失败（已重试 {attempt} 次）：{e}\n"
                    f"提示：思考型模型（DeepSeek-R1/GLM 思考模式等）响应慢，"
                    f"可在设置换非思考模型，或再点一次重试") from None
            wait = 5 * (attempt + 1)
            api_log(f"⚠ 文案请求网络异常（{type(e).__name__}）→ {wait}s 后重试"
                    f"（第 {attempt + 1}/{net_retries} 次）")
            time.sleep(wait)
            last = e
    raise RuntimeError(str(last))


def _balanced_json(t, start, open_ch="{", close_ch="}"):
    """从 t[start]（应为 open_ch）开始找配对 close_ch（正确处理字符串/转义），返回子串或 None。

    贪婪正则（r"\\{.*\\}" 之类）在 JSON 前后还有文本、或文本里有同类括号时会匹配过宽，
    平衡扫描精确取第一个完整块。
    """
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(t)):
        c = t[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return t[start:i + 1]
    return None


def _strip_think(text):
    """思考型模型（deepseek-r1/glm 等）会吐 <think>…</think>，思考里也可能有花括号。"""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def _extract_json(text):
    """从模型输出里抠 JSON：剥 <think> 与代码围栏，整块解析失败再做平衡扫描。"""
    t = _strip_think(text)
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        for m in re.finditer(r"\{", t):
            cand = _balanced_json(t, m.start())
            if cand is not None:
                try:
                    return json.loads(cand)
                except json.JSONDecodeError:
                    continue
        m = re.search(r"\{.*\}", t, flags=re.S)  # 老路径兜底
        if m:
            return json.loads(m.group(0))
        raise


def ai_copywriting(cfg, hint="", style=""):
    """调文案对话模型，产出整套表情文案初稿（name/intro/reward_line/stickers）。

    文案模型配置（text_*）留空时回落到图片组的配置；地址都留空则用 OpenAI 官方。
    返回前做轻清洗：含义词去空格/去重/截 4 字，违禁词配字替换为含义词。
    """
    base = (cfg.get("text_base_url") or cfg.get("base_url") or OPENAI_DEFAULT_BASE).rstrip("/")
    key = cfg.get("text_api_key") or cfg.get("api_key") or ""
    model = cfg.get("text_model") or ""
    if not (key and model):
        raise ValueError("文案模型没配全：设置 → 「文案对话模型」填 API Key 和模型名（接口地址留空 = OpenAI 官方）")
    user = f"角色设定/画风：{style or '抽象梗系表情包角色（大头、默认表情自带态度）'}"
    if hint:
        user += f"\n策划灵感提示：{hint}"
    user += "\n请按系统规则产出整套文案 JSON。"
    # max_tokens 给足：思考型模型的 <think> 也耗 token，太小会把 JSON 截断成废文本
    text = _chat(base, key, model, COPY_SYSTEM, user, max_tokens=6000)
    try:
        data = _extract_json(text)
    except Exception:
        # 自动纠偏重试：模型输出思考文本/格式跑偏时，带着反馈强制再来一次
        user2 = user + ("\n\n⚠ 你上一次的输出没有任何合法 JSON（可能输出了思考过程或设计说明）。"
                        "这次必须直接输出一个 JSON 对象，从 { 开始到 } 结束，"
                        "不要思考过程、不要解释、不要围栏以外的任何文字。")
        text2 = _chat(base, key, model, COPY_SYSTEM, user2, max_tokens=6000)
        try:
            data = _extract_json(text2)
        except Exception:
            raise ValueError(f"模型输出不是合法 JSON（已自动纠偏重试 1 次），换模型或重试。输出开头：{text2[:120]}")

    name = str(data.get("name") or "").strip()
    intro = str(data.get("intro") or "").strip()
    reward = str(data.get("reward_line") or "").strip()
    raw = data.get("stickers") or []
    if not isinstance(raw, list) or len(raw) < 8:
        raise ValueError(f"模型只给出 {len(raw) if isinstance(raw, list) else 0} 张表情，至少要 8 张，请重试")

    seen = set()
    stickers = []
    for s in raw:
        word = re.sub(r"[\s，。！？、,.!?/\\:\"'*<>|]", "", str(s.get("word") or ""))[:4]
        if not word or word in seen:
            continue
        seen.add(word)
        caption = re.sub(r"\s+", "", str(s.get("caption") or "")) or word
        for b in BANNED:
            if b.lower() in caption.lower():
                caption = word
                break
        stickers.append({"word": word, "caption": caption,
                         "action": str(s.get("action") or "waves hello").strip()})
    if len(stickers) < 8:
        raise ValueError(f"清洗后只剩 {len(stickers)} 张有效表情（含义词大量重复），请重试")
    return {"name": name[:8], "intro": intro[:80], "copyright": "",
            "reward_line": reward, "stickers": stickers}


def test_text_connection(cfg):
    """设置页「测试文案模型」：发一条小对话验证连通性。"""
    base = (cfg.get("text_base_url") or cfg.get("base_url") or OPENAI_DEFAULT_BASE).rstrip("/")
    key = cfg.get("text_api_key") or cfg.get("api_key") or ""
    model = cfg.get("text_model") or ""
    if not (key and model):
        return "❌ 未配全：需要 API Key 和模型名（接口地址留空 = OpenAI 官方）"
    try:
        out = _chat(base, key, model, "你是回声机", "回复两个字：正常", max_tokens=2048, timeout=60)
        return f"✅ 文案模型连通，回复：{out[:30]}" if out else "⚠ 连通但模型没吐内容（思考型模型？正常现象，可直接使用）"
    except RuntimeError as e:
        m = str(e)
        if "404" in m:
            if _is_ark_base(base):
                return "❌ 地址路径不对（404）：方舟套餐入口填 …/api/plan，标准入口填 …/api/v3"
            return "❌ 地址路径不对（404）：确认接口地址（OpenAI 兼容地址一般以 /v1 结尾）"
        return f"❌ {m[:180]}"
    except Exception as e:
        return f"❌ {type(e).__name__}: {str(e)[:150]}"


# ---------- 抽象创意参谋 ----------

IDEAS_SYSTEM = (
    "你是「抽象表情包」策划师。效率要求：判断要快、给结果要直接——不要长篇推理、"
    "不要解释设计思路，直接输出 JSON。你的思考时间用户等不起。\n"
    "设计对标熊猫头、金馆长、蘑菇头这类国民级表情包的底层逻辑"
    "（学它们的传播机制，不出这些角色本身）：每张图都是一次社交动作——收到的人愣一下，"
    "然后在下一场对话里把你这张图直接扔出去。衡量标准两条：①能当社交武器用：怼人/认怂/阴阳三选一，"
    "想不出「该在哪句话后面发它」的选题直接淘汰；②造型出人意料。温和、治愈、小清新、"
    "纯造词炫技但没有使用瞬间的，全部等于失败。\n"
    "第一批蹦进脑海的词全部禁用：摸鱼/开摆/躺平/内卷/佛系/社恐/在吗/已读不回/呵呵/装忙/"
    "划水/加班/emo/摆烂，以及任何同质替换词。\n"
    "12 条按社交姿态分三组（姿态是灵魂，词只是外壳）：\n"
    "· 怼人系 ×4：对方先出招，这张图占上风回击——理直气壮的反驳、开玩笑的威胁、看穿一切的凝视\n"
    "· 认怂系 ×4：破防/求饶/摆烂，但摆得理不直气也壮——无赖感、装死、破罐破摔的从容\n"
    "· 阴阳系 ×4：表面客气实则开涮——反向祝福、假装关心、礼貌发疯\n"
    "在姿态之上用错位手法造词（每条至少一种，12 条覆盖至少 4 种）：\n"
    "1. 自造伪术语：包装成医学/学术/科技名词（电子青菜＝被互联网吸干水分的人）\n"
    "2. 物种/物品错位：让动物或物品顶替人的处境（精神水豚＝情绪稳定到麻木的打工人）\n"
    "3. 状态合成词：两个不搭的字硬拼出新概念（班味很重＝带着职场的疲惫气场）\n"
    "4. 具体到荒诞：用精确细节替代泛泛描述（键盘出汗＝紧张到手心冒汗）\n"
    "5. 身体化情绪：心理状态写成身体症状（心口堵车＝焦虑有了实感）\n"
    "6. 反向关心/反向祝福：客气话里藏刀（含班量超标、祝你掉线）\n"
    "每条格式 JSON 对象 {word, scene, why}："
    "word 为表情文案词 1-4 字（无标点、不重复、优先能当「身份」或「回击」用的词）；"
    "scene 写「对方做了什么 → 这张图作为回击/认怂扔出」的具体瞬间，要有对抗感或无赖感，"
    "禁止「上班时」这类概括；例：「朋友发来 60 秒语音方阵，你听了前 5 秒就把手机扣在桌上，扔回这张图」；"
    "why 一句话讲传播钩子（收到的人为什么想转手扔给别人）。\n"
    "主题方向由用户输入决定，无输入时聚焦当代日常（上班/群聊/手机/外卖/睡觉/朋友互怼）。\n"
    "红线：不出明星、影视动漫游戏角色、二创同人；不碰政治敏感与违禁词；"
    "攻击性停留在玩笑级（怼熟人不带脏、不人身攻击）；全部原创。\n"
    "输出纯 JSON 数组，不要 markdown 代码块，不要思考过程和解释文字。"
)


def _repair_truncated_array(t, start):
    """截断的 JSON 数组补救（max_tokens 把输出拦腰切断）：丢最后一个不完整项，补 ']'。

    创意清单是只读建议，丢半条的建议完全可接受——好过整个报错。
    """
    depth = 0
    in_str = False
    esc = False
    last_item_end = -1
    for i in range(start, len(t)):
        c = t[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
            if depth == 0:  # 数组本来就完整（不该到这，上层已试过）
                return t[start:i + 1]
            if depth == 1 and c == "}":  # 顶层项（数组内的对象）完整结束
                last_item_end = i
    if last_item_end > start:
        return t[start:last_item_end + 1] + "]"
    return None


def _extract_json_array(text):
    """从模型输出抠 JSON 数组：剥 <think>/围栏 → 平衡扫描 → 截断修复。"""
    t = _strip_think(text)
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    t = t.strip()
    starts = [m.start() for m in re.finditer(r"\[", t)]
    if not starts:
        arr = json.loads(t)  # 也许整体就是数组字面量变体？让它按原样报错
        return arr if isinstance(arr, list) else []
    for s in starts:
        cand = _balanced_json(t, s, "[", "]")
        if cand is not None:
            arr = json.loads(cand)
            return arr if isinstance(arr, list) else []
    for s in starts:  # 没有完整数组 → 截断修复
        fixed = _repair_truncated_array(t, s)
        if fixed is not None:
            arr = json.loads(fixed)
            return arr if isinstance(arr, list) else []
    raise json.JSONDecodeError("unterminated array", t, len(t))


def ai_ideas(cfg, topic=""):
    """让文案模型出「利于传播的抽象表情」选题清单：[{word, scene, why}]。"""
    base = (cfg.get("text_base_url") or cfg.get("base_url") or OPENAI_DEFAULT_BASE).strip()
    key = (cfg.get("text_api_key") or cfg.get("api_key") or "").strip()
    model = (cfg.get("text_model") or "").strip()
    if not (key and model):
        raise ValueError("文案模型没配全：需要模型名和 API Key（接口地址留空 = OpenAI 官方，设置里第二组）")
    user = f"主题方向（可空）：{topic or '不限，给出当下最容易被转发使用的抽象表情创意'}"
    # 思考型文案模型出 12 条创意常超 2 分钟，超时给足；网络重试只 1 次，
    # 否则慢模型 × 盲目重试会让用户对着「正在出创意」等上十几分钟
    text = _chat(base, key, model, IDEAS_SYSTEM, user, max_tokens=6000, timeout=300, net_retries=1)
    try:
        arr = _extract_json_array(text)
    except Exception:
        # 自动纠偏重试：思考文本/截断/格式跑偏时，带反馈强制再来一次
        user2 = user + ("\n\n⚠ 你上一次的输出解析失败（可能输出了思考过程，或 JSON 被截断）。"
                        "这次必须直接输出一个 JSON 数组，从 [ 开始到 ] 结束，"
                        "不要思考过程、不要解释、不要任何多余文字，12 条尽量精炼。")
        text2 = _chat(base, key, model, IDEAS_SYSTEM, user2, max_tokens=6000, timeout=300, net_retries=1)
        try:
            arr = _extract_json_array(text2)
        except Exception:
            raise ValueError(f"创意输出解析失败（已自动纠偏重试 1 次），换模型或重试。输出开头：{text2[:120]}")
    seen, ideas = set(), []
    for it in arr:
        if not isinstance(it, dict):
            continue
        w = re.sub(r"[\s，。！？、,.!?/\\:\"'*<>|]", "", str(it.get("word", "")).strip())[:4]
        if not w or w in seen:
            continue
        seen.add(w)
        ideas.append({"word": w,
                      "scene": str(it.get("scene", "")).strip()[:60],
                      "why": str(it.get("why", "")).strip()[:60]})
    if len(ideas) < 4:
        raise ValueError(f"可用创意只有 {len(ideas)} 条，再试一次或换个主题方向")
    return ideas


# ---------- 操作（都在 worker 线程里跑）----------

def character_prompt(style, desc=""):
    """第①步角色图提示词：熊猫头式「情绪原型」视觉公式。

    skill 的 cmd_character 写死 cute 全身像——萌则萌矣，但没有传播攻击性。
    表情包的半条命在角色本身：头占比要大（表情是唯一信息载体，脸小了情绪就稀），
    默认表情自带态度（谜之自信/不屑/无赖感——熊猫头的脸底色就是贱，不是友好微笑）。
    这张基准脸会经「same face」传导到全套每张精灵图，所以态度必须从第一步定调。
    desc 为可选的角色描述（穿搭/配饰/气质细节），非空时注入——照片没画出来的
    信息靠文字补：模型会把它融合进识别特征里。
    """
    p = (
        "Turn the subject of this photo into an original, heavily stylized meme-style cartoon sticker character "
        "(think the attitude of classic meme-face characters, do not copy any existing one). "
        "The BIG head with an oversized expressive face is the hero: the face alone must carry the whole emotion. "
        "Tiny simplified body, or head-and-shoulders only, is fine. "
        "The default expression comes with ATTITUDE: smug, cheeky, a little unimpressed, "
        "half-smirking — NOT a friendly smile, NOT cute-for-cute's-sake. "
    )
    if desc.strip():
        p += f"Custom character details (must blend in naturally): {desc.strip()}. "
    p += (
        f"Art style: {style}. "
        "Keep the identifying features (hairstyle, glasses, markings, signature clothing or fur pattern). "
        "It must clearly read as a drawing, never photorealistic. Front-facing, centered, "
        "fully transparent background, no text, no border."
    )
    return p


# ---------- 协作式取消（戒断按钮） ----------

class Cancelled(Exception):
    """用户点了停止。已完成的产物保留，未开跑的跳过。"""


_CANCEL = threading.Event()


def request_cancel():
    """UI 线程调用：请求中止当前任务。正在跑的请求无法打断（socket 阻塞），
    在下一个检查点生效——未开跑的立即跳过，进行中的跑完即弃。"""
    _CANCEL.set()
    api_log("⛔ 收到停止请求：未开跑的任务将跳过，进行中的请求跑完即弃")


def is_cancelled():
    return _CANCEL.is_set()


def reset_cancel():
    """上一任务线程彻底结束后由 UI 清标志，保证下一任务干净开始。"""
    _CANCEL.clear()


def check_cancel(where=""):
    if _CANCEL.is_set():
        raise Cancelled(f"已按你的要求中止{('（' + where + '）') if where else ''}")


def make_character(sticker, cfg, photo, out_path, style, desc=""):
    """照片 → 卡通角色图。

    提示词用 core 的「情绪原型」版（skill 写死 cute 全身像，萌但没攻击性）；
    图片接口路由（方舟/兼容分发）、计费日志 costs.jsonl 仍全部走 skill 底层。
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with env_patch(cfg):
        png = sticker._edit(
            str(photo), character_prompt(style, desc), "1024x1024", "transparent",
            cfg.get("character_model", DEFAULT_CONFIG["character_model"]),
            cfg.get("quality", "medium"),
            out_path.parent / "costs.jsonl",
        )
    out_path.write_bytes(png)
    return {"out": str(out_path), "log": f"角色图已生成：{out_path.name}（情绪原型提示词版）"}


def dry_run(sticker, cfg, pack_dir, with_assets=True):
    """只数要生成几张、估花费，不调 API。角色图缺失时 sys.exit 由调用方接。"""
    p, pack = sticker.load_pack(str(pack_dir))
    jobs = sticker._jobs(p, pack, cfg.get("gen_model", DEFAULT_CONFIG["gen_model"]),
                         cfg.get("quality", "medium"), with_assets, None)
    todo = [j for j in jobs if not j[0].exists()]
    return {"count": len(todo), "usd": round(len(todo) * 0.052, 2), "total": len(jobs)}


def tweak_sheet(sticker, cfg, pack_dir, item, instruction):
    """微调一张已生成的图：参考图换成该图本身，原 prompt + 微调指令，覆盖原图。

    item 形如 "07.png" 或 "07"（精灵图）/"cover.png"（素材）。方舟 seedream 与
    OpenAI edits 接口都以参考图为底改图——画风构图保持，只按指令调整，
    比“重抽”（全随机）可控得多。计费同一次普通生成，log_path 照常记账。
    """
    with env_patch(cfg):
        p, pack = sticker.load_pack(str(pack_dir))
        jobs = sticker._jobs(p, pack, cfg.get("gen_model", DEFAULT_CONFIG["gen_model"]),
                             cfg.get("quality", "medium"), True, None)
        stem = item[:-4] if item.lower().endswith(".png") else item
        job = next((j for j in jobs if j[0].name == f"{stem}.png"), None)
        if job is None:
            raise ValueError(f"{item} 不是可微调的生成项")
        out, _ref, prompt, size, bg, model, quality, log = job
        if not out.exists():
            raise ValueError(f"{out.name} 还没生成过，先「开始生成」再微调")
        inst = instruction.strip()
        if not inst:
            raise ValueError("微调指令不能为空")
        new_prompt = (f"{prompt}\n\n在保持角色形象、画风、构图与参考图一致的前提下做如下微调："
                      f"{inst}。未提及的方面一律保持参考图原样。")
        api_log(f"✎ 微调 {out.name}：{inst}")
        raw = sticker._edit(out, new_prompt, size, bg, model, quality, log)  # 参考图 = 它自己
        out.write_bytes(raw)
        return {"item": out.name, "path": str(out), "bytes": len(raw)}


def gen_pack(sticker, cfg, pack_dir, with_assets=True, redo=None, progress=None):
    """生成精灵图和配套素材（对外入口）。

    必须包在 env_patch 里：接口分发器按“调用时”的 OPENAI_BASE_URL 环境变量
    选方舟/原版接口。漏包会让生成悄悄走错接口——表现为永远“提交中”、
    一条日志都没有（2026-11-09 修复；此前只有 make_character 包了，gen_pack 漏了）。
    """
    with env_patch(cfg):
        return _gen_pack_impl(sticker, cfg, pack_dir, with_assets, redo, progress)


def _gen_pack_impl(sticker, cfg, pack_dir, with_assets=True, redo=None, progress=None):
    """生成主体。progress(item, kind, msg)，kind ∈ ok/fail/count。"""
    p, pack = sticker.load_pack(str(pack_dir))
    redo_set = {int(x) for x in redo if str(x).strip().isdigit()} if redo else None
    jobs = sticker._jobs(p, pack, cfg.get("gen_model", DEFAULT_CONFIG["gen_model"]),
                         cfg.get("quality", "medium"), with_assets, redo_set)
    todo = [j for j in jobs if not j[0].exists()]
    total, done, errors = len(todo), 0, []
    if progress:
        progress(None, "total", str(total))
    if not todo:
        return {"errors": [], "total": 0, "cost": sticker.total_cost(p)}

    def run_one(job):
        check_cancel("排队中")
        return job, sticker._gen_one(job)

    cancelled_out = 0
    with cf.ThreadPoolExecutor(int(cfg.get("jobs") or 4)) as ex:
        futs = {ex.submit(run_one, j): j for j in todo}
        for fut in cf.as_completed(futs):
            job = futs[fut]
            try:
                _, msg = fut.result()
                kind, detail = "ok", msg
            except Cancelled:
                cancelled_out += 1
                kind, detail = "skip", "已停止，跳过"
            except SystemExit as e:  # _edit 缺 key 时 sys.exit
                errors.append(job[0].name)
                kind, detail = "fail", str(e)
            except Exception as e:
                errors.append(job[0].name)
                kind, detail = "fail", f"{type(e).__name__}: {e}"
            done += 1
            if progress:
                progress(job[0].name, kind, detail)
                progress(None, "count", f"{done}/{total}")
    if cancelled_out:
        raise Cancelled(f"已按你的要求中止（完成 {done - cancelled_out}/{total} 张，跳过 {cancelled_out} 张；已生成的都保留在墙上了）")
    return {"errors": errors, "total": total, "cost": sticker.total_cost(p)}


def build_pack(sticker, pack_dir, progress=None):
    """切帧、合 GIF、出投稿包 + 预览 + 文案 + 交付 zip。"""
    p, pack = sticker.load_pack(str(pack_dir))
    sub = p / "submit"
    gifs = sub / "表情图"
    gifs.mkdir(parents=True, exist_ok=True)
    ms = pack.get("frame_ms", 120)
    bg = pack.get("background", "transparent")
    rows = []
    for i, s in enumerate(pack["stickers"], 1):
        check_cancel(f"合成到第 {i} 张")
        sheet = p / "sheets" / f"{i:02d}.png"
        if not sheet.exists():
            if progress:
                progress(f"{i:02d}", "skip", f"缺精灵图 {sheet.name}，先去上一步生成")
            continue
        size, colors, n, border = sticker.build_gif(sheet, gifs / f"{i:02d}.gif", ms, bg, s.get("keep_frames"))
        flag = "  ⚠ 内容压到格子边，重点看这张" if border > 8 else ""
        if progress:
            progress(f"{i:02d}", "ok", f"{s['word']}: {size // 1024}KB {n}帧 {colors}色{flag}")
        rows.append(gifs / f"{i:02d}.gif")
    raw = p / "assets_raw"
    for name, size, fn, kb, alpha in ASSET_SPECS:
        if (raw / f"{name}.png").exists():
            sticker._fit_png(raw / f"{name}.png", size, sub / fn, kb * 1024, alpha)
    sticker._contact_sheet(rows, pack, p / "预览.png")
    sticker._preview_html(pack, p)
    sticker._listing(pack, p)
    with zipfile.ZipFile(p / "交付给客户.zip", "w", zipfile.ZIP_STORED) as z:
        for g in rows:
            z.write(g, f"{pack['stickers'][int(g.stem) - 1]['word']}.gif")
    return {"gifs": [str(g) for g in rows], "submit": str(sub), "cost": sticker.total_cost(p)}


def check_pack(sticker, pack_dir):
    """跑 skill 的微信规范检查，解析 FAIL/WARN。cmd_check 用 sys.exit 报数，这里接住。"""
    ns = argparse.Namespace(pack=str(pack_dir))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            sticker.cmd_check(ns)
        except SystemExit as e:
            if not isinstance(e.code, int) and e.code:
                return {"fails": [str(e.code)], "warns": [], "text": str(e.code)}
    fails, warns = [], []
    for line in buf.getvalue().splitlines():
        if line.startswith("FAIL "):
            fails.append(line[5:])
        elif line.startswith("WARN "):
            warns.append(line[5:])
    return {"fails": fails, "warns": warns, "text": buf.getvalue()}


def get_prompts(sticker, pack_dir):
    """无 API key 模式：返回 [(相对路径, 提示词)]，用户拿去 ChatGPT 手动出图。"""
    p, pack = sticker.load_pack(str(pack_dir))
    items = [(f"sheets/{i:02d}.png（上传角色图，要 1:1 透明底）", sticker._prompt_sheet(pack, s))
             for i, s in enumerate(pack["stickers"], 1)]
    items += [(f"assets_raw/{name}.png（{size}）", prompt)
              for name, (size, _, prompt) in sticker.ASSET_PROMPTS.items()]
    return items


# ---------- 项目管理 ----------

def _skeleton_pack(name, style, frame_ms=120, background="transparent"):
    return {
        "name": name,
        "intro": "",
        "copyright": "",
        "reward_line": "",
        "character": "character.png",
        "style": style,
        "frame_ms": frame_ms,
        "background": background,
        "stickers": [dict(s) for s in DEFAULT_STICKERS],
    }


def new_project(cfg, name):
    p = Path(cfg["packs_dir"]) / name
    p.mkdir(parents=True, exist_ok=True)
    pack = _skeleton_pack(name, cfg.get("style", DEFAULT_CONFIG["style"]),
                          cfg.get("frame_ms", 120), cfg.get("background", "transparent"))
    (p / "pack.json").write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


# ---------- 专辑（系列）模式 ----------

ALBUM_FILE = "album.json"
BAD_DIR_CHARS = '/\\:*?"<>|'


def create_album(cfg, name, style="", desc=""):
    """专辑 = packs/ 下的分组目录 + album.json 元数据；成员套就是里面的普通项目目录。

    core 的生成/合成只认 pack_dir 绝对路径，专辑只是组织层，完全向后兼容：
    散装项目仍在 packs/ 根目录，互不影响。
    """
    name = name.strip()
    if not name or len(name) > 20:
        raise ValueError("专辑名要 1–20 字")
    if any(c in name for c in BAD_DIR_CHARS):
        raise ValueError(f"专辑名不能含这些字符：{BAD_DIR_CHARS}")
    a = Path(cfg["packs_dir"]) / name
    a.mkdir(parents=True, exist_ok=True)
    if (a / ALBUM_FILE).exists():
        raise FileExistsError(f"专辑已存在：{name}")
    meta = {"name": name, "style": style, "desc": desc,
            "created": time.strftime("%Y-%m-%d")}
    (a / ALBUM_FILE).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return a


def new_pack_in_album(cfg, album_dir, pack_name, from_pack=None):
    """在专辑里新建一套。pack.json 的 style 继承专辑 meta；
    from_pack 指定时复制其 character.png，系列形象保持一致。返回 (路径, 是否复制了角色图)。"""
    album_dir = Path(album_dir)
    if not (album_dir / ALBUM_FILE).exists():
        raise ValueError(f"不是专辑目录：{album_dir}")
    meta = json.loads((album_dir / ALBUM_FILE).read_text(encoding="utf-8"))
    pack_name = pack_name.strip()
    if not pack_name:
        raise ValueError("套名不能为空")
    p = album_dir / pack_name
    p.mkdir(parents=True, exist_ok=True)
    if (p / "pack.json").exists():
        raise FileExistsError(f"这套已存在：{pack_name}")
    pack = _skeleton_pack(pack_name, meta.get("style") or cfg.get("style", DEFAULT_CONFIG["style"]),
                          cfg.get("frame_ms", 120), cfg.get("background", "transparent"))
    (p / "pack.json").write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    copied = False
    if from_pack:
        src = Path(from_pack) / "character.png"
        if src.exists():
            shutil.copy2(src, p / "character.png")
            copied = True
    return p, copied


def list_albums(cfg):
    """扫 packs/ 一级子目录：带 album.json 的算专辑，返回 [{meta, path, packs:[{name,path}]}]。"""
    root = Path(cfg["packs_dir"])
    out = []
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir()):
        mf = d / ALBUM_FILE
        if d.is_dir() and mf.exists():
            try:
                meta = json.loads(mf.read_text(encoding="utf-8"))
            except Exception:
                meta = {"name": d.name}
            members = [{"name": s.name, "path": str(s)}
                       for s in sorted(d.iterdir())
                       if s.is_dir() and (s / "pack.json").exists()]
            out.append({"meta": meta, "path": str(d), "packs": members})
    return out


def load_pack_json(pack_dir):
    return json.loads((Path(pack_dir) / "pack.json").read_text(encoding="utf-8"))


def save_pack_json(pack_dir, pack):
    (Path(pack_dir) / "pack.json").write_text(
        json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")


def read_cost(sticker, pack_dir):
    try:
        return sticker.total_cost(Path(pack_dir))
    except Exception:
        return 0.0


def validate_pack(pack):
    """保存前的即时校验（文本规则子集，最终以 check 命令为准）。"""
    fails = []
    name = pack.get("name", "")
    intro = pack.get("intro", "")
    cr = pack.get("copyright", "")
    line = pack.get("reward_line", "")
    if not 1 <= len(name) <= 8 or re.search(r"[\s，。！？、,.!?]", name):
        fails.append(f"表情名称要 1–8 字、无标点无空格（现在 {len(name)} 字）：{name!r}")
    if len(intro) > 80:
        fails.append(f"表情介绍超过 80 字（现在 {len(intro)} 字）")
    if len(cr) > 10:
        fails.append(f"版权信息超过 10 字（现在 {len(cr)} 字）：{cr!r}")
    if line and not 5 <= len(line) <= 15:
        fails.append(f"赞赏引导语要 5–15 字（现在 {len(line)} 字）：{line!r}")
    for field, text in (("名称", name), ("介绍", intro), ("引导语", line)):
        for b in BANNED:
            if b.lower() in text.lower():
                fails.append(f"{field}里有「{b}」，容易被驳回")
    stickers = pack.get("stickers", [])
    if not 8 <= len(stickers) <= 24:
        fails.append(f"一套要 8–24 张，现在 {len(stickers)} 张")
    words = [s.get("word", "") for s in stickers]
    for w in words:
        if len(w) > 4 or re.search(r"[^\w]", w):
            fails.append(f"含义词要 ≤4 字、不带符号：{w!r}")
    for w in {x for x in words if words.count(x) > 1}:
        fails.append(f"含义词重复：{w}")
    for s in stickers:
        for b in BANNED:
            if b.lower() in (s.get("caption") or "").lower():
                fails.append(f"配字里有「{b}」：{s.get('caption')}")
    return fails
