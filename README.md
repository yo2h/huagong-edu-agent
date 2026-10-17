\# 华工教务办事与课表答疑 Agent



基于 DeepSeek Function Calling 的教务办事智能体，面向华南理工大学本科生，支持办事指南检索、课表查询、空教室查询和办事申请预提交。项目为课程设计作品，所有教务数据均为本地模拟，不连接真实教务系统。



\## 功能



\- 办事指南检索：缓考、成绩复核、在读证明、重修、辅修、学分认定等 12 类事项

\- 课表查询：按学号和周次查询课程、时间、地点、教师

\- 空教室查询：按教学楼、星期、时段查询空闲教室

\- 办事申请预提交：信息齐全时生成模拟工单号

\- 异常兜底：缺参追问、API 超时、学号不存在、知识库无匹配

\- 安全护栏：提示注入拦截、越权操作拒绝、超范围请求转人工

\- 全链路 Trace：控制台打印 + `traces/{trace\_id}.json` 落盘



\## 目录结构



```text

.

├── main.py              # 入口

├── agent.py             # Agent 循环、Trace、护栏

├── prompts.py           # System Prompt

├── tools.py             # 工具函数与 Schema

├── data/                # 模拟数据

├── traces/              # 运行后生成

├── Screenshots/         # 报告截图

├── .env.example

├── requirements.txt

└── README.md

