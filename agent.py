# agent.py
import json
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path

from openai import OpenAI

from prompts import SYSTEM_PROMPT
from tools import TOOLS, execute_tool

TRACE_DIR = Path(__file__).parent / "traces"
TRACE_DIR.mkdir(exist_ok=True)

MAX_STEPS = 6          # 最大工具调用步数，防死循环
HISTORY_LIMIT = 20     # 短期记忆最多保留 20 条 user/assistant 消息


# ---------------- 护栏：提示注入 / 越权检测 ----------------
INJECTION_KEYWORDS = [
    "忽略之前", "忽略以上", "忽略所有", "ignore previous", "ignore above",
    "你现在是", "你现在扮演", "管理员模式", "开发者模式", "system prompt",
    "系统提示词", "绕过", "越权", "删除数据库", "清空数据",
]

OVERRIDE_COMBOS = [
    ("改", "成绩"), ("修改", "成绩"), ("把", "成绩", "改"),
    ("价格", "0"), ("免费", "拿"), ("0元",),
    ("别人", "学号"), ("他人", "信息"), ("查询", "别人"), ("别人", "课表"),
]


def check_guardrail(text: str):
    """返回 (是否命中, 原因)"""
    lower = text.lower()
    for kw in INJECTION_KEYWORDS:
        if kw.lower() in lower:
            return True, f"命中提示注入/越权关键词：{kw}"
    for combo in OVERRIDE_COMBOS:
        if all(w in text for w in combo):
            return True, f"命中越权操作组合：{' + '.join(combo)}"
    return False, ""


# ---------------- Trace 记录器 ----------------
class TraceLogger:
    def __init__(self, user_input: str):
        self.trace_id = f"trace_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self.user_input = user_input
        self.start_time = time.time()
        self.steps = []
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.final_answer = ""
        print(f"\n{'=' * 80}\n[trace_id] {self.trace_id}\n[user] {user_input}\n{'=' * 80}")

    def log(self, step_type: str, content: str, extra: dict = None):
        step = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "type": step_type,
            "content": content,
        }
        if extra:
            step.update(extra)
        self.steps.append(step)
        print(f"[{step_type}] {content}")

    def add_usage(self, usage):
        if usage:
            self.total_prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
            self.total_completion_tokens += getattr(usage, "completion_tokens", 0) or 0

    def save(self):
        data = {
            "trace_id": self.trace_id,
            "user_input": self.user_input,
            "start_time": datetime.fromtimestamp(self.start_time).isoformat(timespec="seconds"),
            "end_time": datetime.now().isoformat(timespec="seconds"),
            "latency_ms": int((time.time() - self.start_time) * 1000),
            "steps": self.steps,
            "final_answer": self.final_answer,
            "usage": {
                "prompt_tokens": self.total_prompt_tokens,
                "completion_tokens": self.total_completion_tokens,
                "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
            },
        }
        path = TRACE_DIR / f"{self.trace_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[Trace] 已保存：{path}")


# ---------------- 教务 Agent ----------------
class EduAgent:
    def __init__(self):
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("未找到 DEEPSEEK_API_KEY，请在 .env 中配置")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.history = []  # 只存 user/assistant 最终问答对，避免 tool 消息跨轮配对问题
        self.slots = {}     # 槽位状态，用于 Trace 展示多轮信息补充

    def _extract_slots(self, text: str):
        """简单正则抽取槽位，辅助 Trace 展示；真正的参数抽取由模型完成"""
        if m := re.search(r"\b(\d{8})\b", text):
            self.slots["student_id"] = m.group(1)
        if m := re.search(r"第\s*(\d+)\s*周", text):
            self.slots["week"] = int(m.group(1))
        if m := re.search(r"\b([AB]\d)\b", text):
            self.slots["building"] = m.group(1)
        for d in ["周一", "周二", "周三", "周四", "周五"]:
            if d in text:
                self.slots["day"] = d
        for p in ["上午", "下午", "晚上"]:
            if p in text:
                self.slots["period"] = p

    def _build_messages(self, user_input: str):
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        msgs.extend(self.history[-HISTORY_LIMIT:])
        msgs.append({"role": "user", "content": user_input})
        return msgs

    def run(self, user_input: str):
        trace = TraceLogger(user_input)
        self._extract_slots(user_input)
        trace.log("Slots", json.dumps(self.slots, ensure_ascii=False))

        # 1. 护栏前置检测
        hit, reason = check_guardrail(user_input)
        if hit:
            trace.log("Guardrail", f"拦截：{reason}")
            answer = ("抱歉，我无权执行该操作。教务助手只能提供办事指引、课表/空教室查询和申请预提交，"
                      "不能修改成绩、修改选课、绕过审批或查询他人信息。请通过教务系统正式提交，或联系学院教务员。")
            result = {
                "intent": "reject",
                "need_human": True,
                "human_reason": reason,
                "data": {},
                "answer": answer,
                "disclaimer": "以上信息仅供参考，最终以教务处/学院审核为准。",
            }
            trace.final_answer = answer
            trace.log("Final", answer)
            trace.save()
            self.history.append({"role": "user", "content": user_input})
            self.history.append({"role": "assistant", "content": answer})
            return {"trace_id": trace.trace_id, "structured": result, "raw_answer": answer, "usage": {}}

        # 2. Agent 主循环
        messages = self._build_messages(user_input)
        final_text = ""

        for step in range(1, MAX_STEPS + 1):
            t0 = time.time()
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto",
                    temperature=0.1,
                )
            except Exception as e:
                trace.log("ModelError", f"模型调用失败：{e}")
                final_text = "抱歉，教务助手暂时不可用，请稍后重试或联系学院教务员。"
                break

            latency = int((time.time() - t0) * 1000)
            trace.add_usage(resp.usage)
            msg = resp.choices[0].message

            # 分支 A：模型请求调用工具
            if msg.tool_calls:
                thought = msg.content or "（模型未输出文字，直接请求调用工具）"
                trace.log("Thought", thought, {"step": step, "latency_ms": latency})

                assistant_msg = {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                }
                messages.append(assistant_msg)

                for tc in msg.tool_calls:
                    name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}
                        observation = json.dumps(
                            {"ok": False, "error_type": "invalid_arg",
                             "error": "工具参数不是合法 JSON"}, ensure_ascii=False)
                        trace.log("Action", f"{name}(参数解析失败)", {"step": step})
                        trace.log("Observation", observation, {"step": step})
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": observation})
                        continue

                    trace.log("Action", f"{name}({json.dumps(args, ensure_ascii=False)})",
                              {"step": step, "tool": name, "args": args})

                    t1 = time.time()
                    observation = execute_tool(name, args)
                    tool_latency = int((time.time() - t1) * 1000)

                    trace.log("Observation", observation,
                              {"step": step, "tool": name, "latency_ms": tool_latency})
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": observation})
                continue

            # 分支 B：模型不再调用工具，得到最终答复
            final_text = msg.content or ""
            trace.log("Final", final_text, {"step": step, "latency_ms": latency})
            break
        else:
            # 循环跑满 MAX_STEPS 仍未结束，强制终止
            final_text = "抱歉，本次查询步骤过多，已自动终止。请缩小问题范围后重试，或联系学院教务员。"
            trace.log("MaxSteps", final_text)

        # 3. 解析最终答复中的结构化 JSON
        structured = self._extract_json(final_text)
        if not structured:
            structured = {
                "intent": "unknown",
                "need_human": False,
                "human_reason": "",
                "data": {},
                "answer": final_text,
                "disclaimer": "以上信息仅供参考，最终以教务处/学院审核为准。",
            }
        else:
            structured.setdefault("answer", final_text)
            structured.setdefault("disclaimer", "以上信息仅供参考，最终以教务处/学院审核为准。")

        trace.final_answer = final_text
        trace.save()

        # 4. 更新短期记忆：只保留最终问答对
        self.history.append({"role": "user", "content": user_input})
        self.history.append({"role": "assistant", "content": final_text})
        if len(self.history) > HISTORY_LIMIT:
            self.history = self.history[-HISTORY_LIMIT:]

        return {
            "trace_id": trace.trace_id,
            "structured": structured,
            "raw_answer": final_text,
            "usage": {
                "prompt_tokens": trace.total_prompt_tokens,
                "completion_tokens": trace.total_completion_tokens,
                "total_tokens": trace.total_prompt_tokens + trace.total_completion_tokens,
            },
        }

    @staticmethod
    def _extract_json(text: str):
        """从最终答复中提取 ```json ... ``` 代码块，解析失败返回 None"""
        m = re.search(r"```json\s*(.*?)\s*```", text, re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
