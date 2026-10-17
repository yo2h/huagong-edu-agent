from tools import search_guide, query_schedule, query_empty_classroom, submit_application
print(search_guide("缓考怎么申请"))
print(query_schedule("20230001", 8))
print(query_empty_classroom("A3", "周三", "下午"))
print(submit_application("缓考", "20230001", "数据结构期中考试因病申请缓考"))
print(query_schedule("99999999", 8))   # 应返回 timeout
