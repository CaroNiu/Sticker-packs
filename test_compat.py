# -*- coding: utf-8 -*-
"""回归测试：开源通用化——不锁定任何模型厂商，任意 OpenAI 兼容大模型可用。

要求：默认配置面向 OpenAI 官方；接口地址留空自动回落 api.openai.com；
方舟（volces.com）按 base_url 自动路由 JSON 适配，其余一律走 OpenAI 兼容
multipart 链路且日志为中性提示（不误导非方舟用户去「排查」）。
"""
import io
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core  # noqa: E402

# --- PASS 1: 默认配置面向 OpenAI 官方（开源用户零改动可跑通的基准） ---
assert core.DEFAULT_CONFIG["gen_model"] == "gpt-image-1"
assert core.DEFAULT_CONFIG["character_model"] == "gpt-image-1"
assert core.DEFAULT_CONFIG["text_model"] == "gpt-4o-mini"
assert core.DEFAULT_CONFIG["base_url"] == ""
assert core.OPENAI_DEFAULT_BASE == "https://api.openai.com/v1"
# 方舟识别：只有 volces.com 走 JSON 适配，其余（含空/任意网关）一律 OpenAI 兼容链路
assert core._is_ark_base("https://ark.cn-beijing.volces.com/api/v3")
assert core._is_ark_base("https://ark.cn-beijing.volces.com/api/plan/v3")
assert not core._is_ark_base("https://api.openai.com/v1")
assert not core._is_ark_base("")
assert not core._is_ark_base("https://one.example.com/v1")
print("PASS 1 默认配置面向 OpenAI 官方；_is_ark_base 只认 volces.com")

# --- PASS 2: 文案/创意接口地址留空 → 自动回落 OpenAI 官方 ---
calls = []
COPY_OBJ = {"name": "测试套", "intro": "测试介绍", "reward_line": "谢谢支持啦",
            "stickers": [{"word": f"词{i}", "caption": f"词{i}", "action": "waves hello"}
                         for i in range(1, 13)]}
IDEAS_ARR = [{"word": f"梗{i}", "scene": f"具体瞬间{i}", "why": f"钩子{i}"} for i in range(1, 13)]


def _fake_copy(base, key, model, system, user, max_tokens=3000, timeout=180):
    calls.append(base)
    return json.dumps(COPY_OBJ, ensure_ascii=False)


def _fake_ideas(base, key, model, system, user, max_tokens=3000, timeout=180, net_retries=3):
    calls.append(base)
    return json.dumps(IDEAS_ARR, ensure_ascii=False)


cfg_bare = {**core.DEFAULT_CONFIG, "text_api_key": "k",
            "base_url": "", "text_base_url": ""}
core._chat = _fake_copy
core.ai_copywriting(cfg_bare, hint="", style="")
core._chat = _fake_ideas
core.ai_ideas(cfg_bare)
assert calls and all(b == "https://api.openai.com/v1" for b in calls), calls
print("PASS 2 接口地址留空自动回落 OpenAI 官方（文案+创意两链路）")

# --- PASS 3: 接口分发——volces 走方舟 JSON，其余走 OpenAI 兼容 multipart ---
sticker = core.load_sticker(core.DEFAULT_CONFIG["skill_dir"])
tmp = Path(tempfile.mkdtemp(prefix="compat_"))
(tmp / "x.png").write_bytes(b"\x89PNG\r\n\x1a\n")  # 内容无所谓，fake 不读

ark_calls, compat_calls = [], []


def fake_ark(image_path, prompt, size, background, model, log_path):
    ark_calls.append(model)
    return b"png"


def fake_compat(image_path, prompt, size, background, model, quality, log_path):
    compat_calls.append(model)
    return b"png"


core._edit_ark = fake_ark
sticker._edit_openai_compat = fake_compat

os.environ["OPENAI_BASE_URL"] = "https://ark.cn-beijing.volces.com/api/v3"
os.environ["OPENAI_API_KEY"] = "k"
sticker._edit(str(tmp / "x.png"), "p", "1024x1024", "transparent", "doubao-seedream", "medium", "l")
assert len(ark_calls) == 1 and not compat_calls, (ark_calls, compat_calls)

os.environ["OPENAI_BASE_URL"] = "https://api.openai.com/v1"
sticker._edit(str(tmp / "x.png"), "p", "1024x1024", "transparent", "gpt-image-1", "medium", "l")
assert len(compat_calls) == 1 and len(ark_calls) == 1, (ark_calls, compat_calls)
os.environ.pop("OPENAI_BASE_URL", None)
os.environ.pop("OPENAI_API_KEY", None)
print("PASS 3 接口分发：volces→方舟 JSON，其余→OpenAI 兼容 multipart（中性日志）")

print("COMPAT PASS")
