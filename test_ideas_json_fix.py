# -*- coding: utf-8 -*-
"""回归测试：创意参谋输出截断/思考文本时，_extract_json_array 加固 + 自动纠偏重试能救回。

线上现象（2026-11-10）：JSONDecodeError: Unterminated string starting at: line 8
column 48 —— 文案模型输出被 max_tokens(3000) 截断，JSON 断在字符串中间，
_extract_json_array 只有围栏剥离+贪婪正则，直接裸炸到界面。
修复：剥 <think>、平衡扫描、截断修复（丢最后不完整项补 ]）、max_tokens 6000、
失败自动带反馈重试一次。
"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import core  # noqa: E402

WORDS = ["摸鱼", "开摆", "已读不回", "在吗", "下班", "装忙", "划水",
         "佛系", "躺平", "呵呵", "好的", "收到"]
IDEAS = [{"word": w, "scene": f"场景{w}", "why": f"理由{w}"} for w in WORDS]


def _fake_chat(responses, calls):
    def fake(base, key, model, system, user, max_tokens=3000, timeout=120):
        calls.append({"user": user, "max_tokens": max_tokens})
        return responses[min(len(calls), len(responses)) - 1]
    return fake


cfg = {**core.DEFAULT_CONFIG, "text_api_key": "test-key",
       "text_base_url": "http://mock", "text_model": "mock-chat"}

# --- PASS 1: 截断数组（线上场景）→ 截断修复救回大部分条目 ---
calls = []
full = json.dumps(IDEAS, ensure_ascii=False)
truncated = full[:full.index("佛系") + len("佛系") + 20]  # 在第 8 条的字符串中间拦腰切断
core._chat = _fake_chat([truncated], calls)
ideas = core.ai_ideas(cfg, topic="上班摸鱼")
assert len(ideas) >= 4, f"截断修复后应保留 ≥4 条，实际 {len(ideas)}"
assert ideas[0]["word"] == "摸鱼"
assert len(calls) == 1 and calls[0]["max_tokens"] == 6000, f"应一次调用 max_tokens=6000：{calls}"
print(f"PASS 1 截断数组：修复救回 {len(ideas)} 条（被切断在第 8 条字符串中间）")

# --- PASS 2: <think> 块 + 完整数组 → 剥离解析 ---
calls = []
think_out = ("<think>要出12个抽象梗……摸鱼、开摆……({\"word\": \"假\"}这种不能干扰)</think>\n"
             "好的，以下是创意：\n" + json.dumps(IDEAS, ensure_ascii=False) + "\n以上。")
core._chat = _fake_chat([think_out], calls)
ideas = core.ai_ideas(cfg)
assert len(ideas) >= 10, f"完整数组应全部保留，实际 {len(ideas)}"
print(f"PASS 2 think块+前后文本：平衡扫描解析成功（{len(ideas)} 条）")

# --- PASS 3: 纯思考无数组 → 自动带反馈重试成功 ---
calls = []
ramble = ("Let me brainstorm meme sticker ideas for slacking at work. "
          "Ideas include slacking off, lying flat, pretending to be busy... "
          "I will format them as JSON next.")
core._chat = _fake_chat([ramble, json.dumps(IDEAS, ensure_ascii=False)], calls)
ideas = core.ai_ideas(cfg)
assert len(ideas) >= 10 and len(calls) == 2, f"{len(ideas)} / {len(calls)} 次调用"
assert "解析失败" in calls[1]["user"], "重试请求应带纠偏反馈"
print("PASS 3 纯思考无数组：自动纠偏重试一次成功")

# --- PASS 4: 两次都失败 → ValueError 带“已自动纠偏重试” ---
calls = []
core._chat = _fake_chat([ramble, ramble], calls)
try:
    core.ai_ideas(cfg)
    raise AssertionError("两次失败应抛 ValueError")
except ValueError as e:
    assert "已自动纠偏重试" in str(e), str(e)
assert len(calls) == 2
print("PASS 4 两次失败：ValueError 明确提示已重试过")

# --- PASS 5: 对象路径回归——_balanced_json 通用化后 _extract_json 仍正常 ---
obj = core._extract_json('废话 {"a": "含\\"引号} 和 } 的字符串", "b": [1,2]} 废话}')
assert obj == {"a": '含"引号} 和 } 的字符串', "b": [1, 2]}, obj
print("PASS 5 _extract_json 对象路径回归正常（转义+嵌套括号）")

core._chat = None
print("IDEAS JSON FIX PASS")
