from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import json
import datetime
import os

app = FastAPI()

# 允许跨域，方便你的 Hexo 博客直接调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================= 1. 数据加载与基础配置 =================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(BASE_DIR, "school_timetable.json"), "r", encoding="utf-8") as f:
    timetable = json.load(f)

try:
    with open(os.path.join(BASE_DIR, "exam_timetable.json"), "r", encoding="utf-8") as f:
        exam_timetable = json.load(f)
except FileNotFoundError:
    exam_timetable = []

all_classrooms = sorted(list(set(item["classroom"] for item in timetable)))

CAMPUS_DATA = {
    "西土城本部": {
        "教二": ["2-"],
        "教三": ["3-"],
        "教四": ["4-"],
        "主楼": ["未来学习大楼"]
    },
    "沙河校区": {
        "教学实验综合楼N": ["综合楼-N", "教学实验综合楼-N"],
        "教学实验综合楼S": ["综合楼-S", "教学实验综合楼-S"],
        "智慧教学楼（S1）": ["智慧教学楼", "智慧"]
    }
}

def get_classroom_location(room_name):
    for campus, buildings in CAMPUS_DATA.items():
        for b_name, keywords in buildings.items():
            for kw in keywords:
                if kw in ["未来学习大楼", "智慧教学楼", "教学实验综合楼-N", "教学实验综合楼-S"]:
                    if kw in room_name: return campus, b_name
    for campus, buildings in CAMPUS_DATA.items():
        for b_name, keywords in buildings.items():
            for kw in keywords:
                if kw not in ["未来学习大楼", "智慧教学楼", "教学实验综合楼-N", "教学实验综合楼-S"]:
                    if room_name.startswith(kw): return campus, b_name
    return "其他", "其他"

# ================= 2. 时间计算逻辑 =================
ANCHOR_DATE = datetime.date(2026, 5, 29)
ANCHOR_WEEK = 13

PERIOD_TIMING = {
    1:  ("08:00", "08:45"), 2:  ("08:50", "09:35"), 3:  ("09:50", "10:35"),
    4:  ("10:40", "11:25"), 5:  ("11:30", "12:15"), 6:  ("13:00", "13:45"),
    7:  ("13:50", "14:35"), 8:  ("14:45", "15:30"), 9:  ("15:40", "16:25"),
    10: ("16:35", "17:20"), 11: ("17:25", "18:10"), 12: ("18:30", "19:15"),
    13: ("19:20", "20:05"), 14: ("20:10", "20:55"),
}

def get_bj_now():
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    return utc_now.replace(tzinfo=None) + datetime.timedelta(hours=8)

def get_current_school_time():
    bj_today = get_bj_now().date()
    delta_days = (bj_today - ANCHOR_DATE).days
    current_weekday = (4 + delta_days) % 7 + 1
    anchor_monday = ANCHOR_DATE - datetime.timedelta(days=4)
    delta_weeks = (bj_today - anchor_monday).days // 7
    return max(1, ANCHOR_WEEK + delta_weeks), current_weekday

def get_current_period_index():
    now_str = get_bj_now().strftime("%H:%M")
    for period, (start, end) in PERIOD_TIMING.items():
        if start <= now_str <= end: return period
    return None

# ================= 3. 核心双重过滤算法 =================
def find_empty_rooms_multi_periods(target_week, target_weekday, selected_periods, selected_buildings):
    if not selected_periods: return []
    
    weeks_delta = target_week - ANCHOR_WEEK
    target_date = ANCHOR_DATE - datetime.timedelta(days=4) + datetime.timedelta(weeks=weeks_delta, days=target_weekday-1)
    target_date_str = target_date.strftime("%Y-%m-%d")
    target_date_str_slash = target_date.strftime("%Y/%m/%d")
    
    busy_rooms = set()
    
    # 课表过滤
    for item in timetable:
        if item["weekday"] == target_weekday and item["period"] in selected_periods:
            weeks_str = item["weeks"]
            is_busy = False
            for part in weeks_str.split(','):
                if '-' in part:
                    s, e = map(int, part.split('-'))
                    if s <= target_week <= e: is_busy = True
                else:
                    if part.isdigit() and int(part) == target_week: is_busy = True
            if is_busy: busy_rooms.add(item["classroom"])

    # 考表过滤
    for exam in exam_timetable:
        if exam["date"] in [target_date_str, target_date_str_slash]:
            has_overlap = any(p in selected_periods for p in exam["periods"])
            if has_overlap: busy_rooms.add(exam["classroom"])
                                
    filtered_empty = []
    for room in all_classrooms:
        _, b_name = get_classroom_location(room)
        if b_name in selected_buildings and room not in busy_rooms:
            filtered_empty.append(room)
    return filtered_empty

# ================= 4. API 路由接口定义 =================

@app.get("/api/init-time")
def init_time():
    """新路由：让前端一打开网页，就能自动同步获取当前的北京时间、周次、第几节课"""
    auto_week, auto_weekday = get_current_school_time()
    current_live_period = get_current_period_index()
    return {
        "now_time": get_bj_now().strftime("%Y-%m-%d %H:%M:%S"),
        "auto_week": auto_week,
        "auto_weekday": auto_weekday,
        "current_live_period": current_live_period
    }

@app.get("/api/classroom")
def query_classroom(
    week: int = Query(..., description="周次"),
    weekday: int = Query(..., description="星期几"),
    periods: str = Query(..., description="节次，逗号分隔，如 1,2,3"),
    buildings: str = Query(..., description="楼名，逗号分隔，如 教三,教四")
):
    """主查询路由：接收前端传来的筛选参数，返回空教室列表"""
    period_list = [int(p) for p in periods.split(",") if p.isdigit()]
    building_list = [b.strip() for b in buildings.split(",") if b.strip()]
    
    # 运行过滤算法
    rooms = find_empty_rooms_multi_periods(week, weekday, period_list, building_list)
    
    # 按教学楼归类好，方便前端直接排版渲染
    result_dict = {b: [] for b in building_list}
    for room in rooms:
        _, b_name = get_classroom_location(room)
        if b_name in result_dict:
            result_dict[b_name].append(room)
            
    return {
        "status": "success",
        "query_info": {"week": week, "weekday": weekday, "periods": period_list},
        "rooms": result_dict
    }

# 引入桥梁包
from mangum import Mangum

# 包装 FastAPI 实例，Vercel 会自动寻找 handler 变量作为入口
handler = Mangum(app)