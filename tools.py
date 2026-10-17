# tools.py
import json
import random
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


def _load(name):
    """读取 data 目录下的 json 文件"""
    with open(DATA_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


# ============ 工具函数（全部返回 dict，方便 Agent 判断） ============

def search_guide(query: str):
    """关键词检索办事指南，返回匹配度最高的前 2 条"""
    guides = _load("guides.json")
    query = query.lower()
    scored = []
    for g in guides:
        score = 0
        for kw in g["keywords"]:
            if kw.lower() in query:
                score += 2
        if g["title"].lower() in query:
            score += 3
        if score > 0:
            scored.append((score, g))
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        return {"ok": False, "error_type": "not_found",
                "error": "知识库未检索到该事项，请转人工或换关键词"}
    results = [g for _, g in scored[:2]]
    return {"ok": True, "data": results}


def query_schedule(student_id: str, week: int):
    """查询课表。特殊学号用于异常测试：99999999=超时，00000000=不存在"""
    if student_id == "99999999":
        return {"ok": False, "error_type": "timeout",
                "error": "课表系统响应超时（模拟 504），请稍后重试"}
    schedules = _load("schedules.json")
    stu = schedules.get(student_id)
    if not stu:
        return {"ok": False, "error_type": "not_found",
                "error": f"学号 {student_id} 不存在，请核对后重试"}
    courses = []
    for c in stu["courses"]:
        if c["start_week"] <= week <= c["end_week"]:
            courses.append({
                "course": c["course"],
                "time": c["time"],
                "location": c["location"],
                "teacher": c["teacher"],
            })
    if not courses:
        return {"ok": True, "data": {"student": stu["name"], "week": week,
                                     "courses": [], "note": "该周无课"}}
    return {"ok": True, "data": {"student": stu["name"], "week": week,
                                 "courses": courses}}


def query_empty_classroom(building: str, day: str, period: str):
    """查询空教室。building 如 A3；day 如 周三；period 如 下午"""
    rooms_data = _load("classrooms.json")
    b = rooms_data.get(building)
    if not b:
        return {"ok": False, "error_type": "not_found",
                "error": f"未找到教学楼 {building}，目前支持：{list(rooms_data.keys())}"}
    if day not in ["周一", "周二", "周三", "周四", "周五"]:
        return {"ok": False, "error_type": "invalid_arg", "error": f"day 参数不合法：{day}"}
    if period not in ["上午", "下午", "晚上"]:
        return {"ok": False, "error_type": "invalid_arg", "error": f"period 参数不合法：{period}"}
    occupied = set()
    for o in b["occupied"]:
        if o["day"] == day and o["period"] == period:
            occupied.add(o["room"])
    empty = [r for r in b["rooms"] if r not in occupied]
    return {"ok": True, "data": {"building": building, "day": day,
                                 "period": period, "empty_rooms": empty}}


def submit_application(app_type: str, student_id: str, detail: str):
    """预提交办事申请，生成模拟工单号"""
    allowed = ["缓考", "成绩复核", "在读证明", "重修", "教室借用"]
    if app_type not in allowed:
        return {"ok": False, "error_type": "rejected",
                "error": f"不支持的事项类型：{app_type}，仅支持 {allowed}"}
    if len(student_id) != 8 or not student_id.isdigit():
        return {"ok": False, "error_type": "invalid_arg",
                "error": "学号必须为 8 位数字"}
    if len(detail.strip()) < 5:
        return {"ok": False, "error_type": "invalid_arg",
                "error": "申请说明过短，请至少补充 5 个字的原因或课程信息"}
    schedules = _load("schedules.json")
    if student_id not in schedules:
        return {"ok": False, "error_type": "not_found",
                "error": f"学号 {student_id} 不存在，无法提交"}
    ticket_id = f"TICKET-20261018-{random.randint(1000, 9999)}"
    return {"ok": True, "data": {"ticket_id": ticket_id, "app_type": app_type,
                                 "student_id": student_id, "status": "待教务审核",
                                 "note": "请按指南准备材料，并在 3 个工作日内关注审核结果"}}


# ============ OpenAI / DeepSeek Function Calling Schema ============

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_guide",
            "description": "检索华南理工大学教务办事指南。当学生询问办理条件、所需材料、流程、截止时间或办理地点时调用。不要凭记忆回答办事规则。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索关键词，如“缓考申请”“成绩复核”“在读证明”"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_schedule",
            "description": "查询指定学生指定周次的课表。必须同时获得学号和周次后才能调用；缺任意一项应先追问。",
            "parameters": {
                "type": "object",
                "properties": {
                    "student_id": {"type": "string", "description": "8 位学号"},
                    "week": {"type": "integer", "description": "教学周次，1-20"},
                },
                "required": ["student_id", "week"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_empty_classroom",
            "description": "查询某教学楼某星期某时段的空教室。三个参数必须齐全，缺任意一项应先追问。",
            "parameters": {
                "type": "object",
                "properties": {
                    "building": {"type": "string", "description": "教学楼编号，如 A3"},
                    "day": {"type": "string", "enum": ["周一", "周二", "周三", "周四", "周五"]},
                    "period": {"type": "string", "enum": ["上午", "下午", "晚上"]},
                },
                "required": ["building", "day", "period"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_application",
            "description": "预提交教务办事申请并生成工单号。仅在学生明确要求提交/申请，且事项类型、学号、申请说明三项齐全时调用。不用于普通咨询。",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_type": {"type": "string", "enum": ["缓考", "成绩复核", "在读证明", "重修", "教室借用"]},
                    "student_id": {"type": "string", "description": "8 位学号"},
                    "detail": {"type": "string", "description": "申请说明，包含课程名、原因等，至少 5 个字"},
                },
                "required": ["app_type", "student_id", "detail"],
            },
        },
    },
]

# 工具名 -> 函数 的映射，供 agent loop 调用
TOOL_FUNCS = {
    "search_guide": search_guide,
    "query_schedule": query_schedule,
    "query_empty_classroom": query_empty_classroom,
    "submit_application": submit_application,
}


def execute_tool(name, args):
    """统一执行入口：捕获异常，返回 JSON 字符串给模型"""
    try:
        func = TOOL_FUNCS.get(name)
        if not func:
            return json.dumps({"ok": False, "error_type": "unknown_tool",
                               "error": f"未知工具：{name}"}, ensure_ascii=False)
        result = func(**args)
        return json.dumps(result, ensure_ascii=False)
    except TypeError as e:
        return json.dumps({"ok": False, "error_type": "invalid_arg",
                           "error": f"参数错误：{e}"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"ok": False, "error_type": "internal_error",
                           "error": f"工具内部错误：{e}"}, ensure_ascii=False)
