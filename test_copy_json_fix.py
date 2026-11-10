# -*- coding: utf-8 -*-
"""回归测试：文案模型输出思考文本/格式跑偏时，_extract_json 加固 + 自动纠偏重试能救回。

线上现象（2026-11-09）：文案模型输出 "Let me design a sticker pack based on the
character: ..." 而不是 JSON，ai_copywriting 直接 ValueError 让用户"换模型或重试"。
修复：①剥 <think> 块；②平衡扫描取第一个完整 JSON 对象（JSON 前后有废话也能抠出）；
③max_tokens 6000（思考也耗 token，3000 会截断）；④失败带反馈自动重试一次。
"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import core  # noqa: E402

PACK = {"name": "摸鱼猫", "intro": "一只上班摸鱼的猫", "reward_line": "摸鱼快乐",
        "stickers": [{"word": w, "caption": w, "action": f"doing {w} pose"}
                     for w in ("你好", "好的", "稍等", "哈哈", "无语", "谢谢",
                               "抱抱", "摸鱼", "下班")]}


def _fake_chat(responses, calls):
    def fake(base, key, model, system, user, max_tokens=3000, timeout=180):
        calls.append({"user": user, "max_tokens": max_tokens})
        return responses[min(len(calls), len(responses)) - 1]
    return fake


cfg = {**core.DEFAULT_CONFIG, "text_api_key": "test-key",
       "text_base_url": "http://mock", "text_model": "mock-chat"}

# --- PASS 1: 思考文本 + 后置 JSON（用户线上场景）→ 平衡扫描救回，一次调用 ---
calls = []
core._chat = _fake_chat(
    ['Let me design a sticker pack based on the character: cute chibi, two-head-tall, '
     'thick clean dark outlines. The pack will have nine stickers covering daily replies. '
     + json.dumps(PACK, ensure_ascii=False) + " Hope this helps!"], calls)
data = core.ai_copywriting(cfg, hint="职场摸鱼", style="可爱Q版")
assert data["name"] == "摸鱼猫" and len(data["stickers"]) == 9
assert len(calls) == 1 and calls[0]["max_tokens"] == 6000, f"应为一次调用且 max_tokens=6000：{len(calls)}"
print("PASS 1 思考文本+后置 JSON：平衡扫描抠出，一次调用成功")

# --- PASS 2: <think> 块（思考型模型）→ 剥离后解析 ---
calls = []
think_out = ("<think>用户想要表情包，我需要设计9个词……先想想要哪些词：你好、好的……"
             "这里有个花括号例子 {\"word\": \"假\"} 不能干扰解析</think>\n"
             + "```json\n" + json.dumps(PACK, ensure_ascii=False) + "\n```")
core._chat = _fake_chat([think_out], calls)
data = core.ai_copywriting(cfg)
assert data["name"] == "摸鱼猫" and len(data["stickers"]) == 9
print("PASS 2 <think>块+围栏：剥离后解析成功，think 里的花括号不干扰")

# --- PASS 3: 纯思考无 JSON → 第一次失败，自动带反馈重试成功 ---
calls = []
ramble = ("Sure! Let me think about this sticker pack step by step. "
          "First, the character is a cute cat. Second, we need daily replies... "
          "I will write the JSON next.")  # 全程无 JSON
core._chat = _fake_chat([ramble, json.dumps(PACK, ensure_ascii=False)], calls)
data = core.ai_copywriting(cfg)
assert data["name"] == "摸鱼猫"
assert len(calls) == 2, f"应自动重试一次（实际 {len(calls)} 次调用）"
assert "合法 JSON" in calls[1]["user"], "重试请求应带纠偏反馈"
print("PASS 3 纯思考无 JSON：自动纠偏重试一次成功，反馈已注入")

# --- PASS 4: 两次都无 JSON → ValueError 且带“已自动纠偏重试” ---
calls = []
core._chat = _fake_chat([ramble, ramble], calls)
try:
    core.ai_copywriting(cfg)
    raise AssertionError("两次都失败应抛 ValueError")
except ValueError as e:
    assert "已自动纠偏重试" in str(e), str(e)
assert len(calls) == 2
print("PASS 4 两次失败：ValueError 明确提示已重试过")

core._chat = None  # 防御：确保后续无残留引用
print("COPY JSON FIX PASS")
