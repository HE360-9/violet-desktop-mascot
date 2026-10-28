import requests
import json
import time
import os
import traceback

CACHE_DIR = "./cache"
os.makedirs(CACHE_DIR, exist_ok=True)
CACHE_EXPIRE = 21600
COOLDOWN = 600
MIN_REQ_GAP = 3.0  

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
})

city_last_req = dict()
_last_global_http = 0.0

def _wait_http_gap():
    global _last_global_http
    now = time.time()
    diff = now - _last_global_http
    if diff < MIN_REQ_GAP:
        time.sleep(MIN_REQ_GAP - diff)
    _last_global_http = time.time()

def read_cache(cache_name:str):
    cache_path = os.path.join(CACHE_DIR, f"{cache_name}.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if time.time() - data.get('times', 0) < CACHE_EXPIRE:
                    return data.get('content'), data.get("times",0)
        except Exception:
            pass
    return None, 0

def write_cache(cache_name:str,content:str):
    cache_path = os.path.join(CACHE_DIR, f"{cache_name}.json")
    save_path={
        "content":content,
        "times":time.time()
    }
    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(save_path, f, ensure_ascii=False,indent=2)

def weather(city:str)->str:
    cache_name = f"weather_{city}"
    content, cache_ts = read_cache(cache_name)
    last_time = city_last_req.get(city, 0)
    if content and time.time() - last_time < COOLDOWN:
        return content
    try:
        _wait_http_gap()
        url = f"https://wttr.in/{city}?format=4&lang=zh"
        response = SESSION.get(url,timeout=5)
        content = response.text[:1000].strip()
        write_cache(cache_name,content)
        city_last_req[city] = time.time()
        return content
    except Exception as e:
        traceback.print_exc()
        return "客人，很抱歉，获取该地天气信息失败，暂时无法为您播报。"

def hot_news()->str:
    cache_name = "hot_news"
    content, cache_ts = read_cache(cache_name)
    current_ts = time.time()
    if content and (current_ts - cache_ts) < COOLDOWN:
        return content
    try:
        _wait_http_gap()
        url = "https://api.bilibili.com/x/web-interface/ranking/v2?rid=0"
        resp = SESSION.get(url,timeout=10)

        if resp.text.strip().startswith("<!DOCTYPE"):
            raise ValueError("接口返回HTML页面")
        js = resp.json()
        if js.get("code") != 0:
            raise ValueError(f"B站接口错误码 {js.get('code')}")
        video_list = js["data"]["list"]
        out = []
        for idx,item in enumerate(video_list[:5],1):
            title = item.get("title","").strip()
            play = item.get("play","")
            if title:
                out.append(f"{idx}. {title} 【播放:{play}】")
        if not out:
            raise ValueError("榜单为空")
        res_text = "\n".join(out)
        write_cache(cache_name,res_text)
        return res_text
    except Exception as e:
        traceback.print_exc()
        return "客人，很抱歉，当前连接资讯站点出现故障，暂时无法获取热点。"

def money()->str:
    cache_name = "money"
    content, cache_ts = read_cache(cache_name)
    current_ts = time.time()
    if content and (current_ts - cache_ts) < COOLDOWN:
        return content

    # akshare 会连带拉起 pandas 等一堆大库（约 80MB 内存、启动慢半秒），
    # 只在真的问汇率/金价时才导入
    import akshare as ak

    out_lines = []
    try:
        _wait_http_gap()
        df_usd = ak.fx_quote_baidu(symbol="美元")
        price_usd = df_usd.iloc[0]["现价"]
        out_lines.append(f"美元兑人民币：{price_usd}")
    except Exception as e:
        traceback.print_exc()
        out_lines.append("美元汇率获取失败")

    try:
        df_jpy = ak.fx_quote_baidu(symbol="日元")
        price_jpy = df_jpy.iloc[0]["现价"]
        out_lines.append(f"日元兑人民币：{price_jpy}")
    except Exception as e:
        traceback.print_exc()
        out_lines.append("日元汇率获取失败")

    try:
        df_gold = ak.spot_hist_sge(symbol="Au99.99")
        latest = df_gold.iloc[-1]
        gold_price = latest["close"]
        gold_date = str(latest["date"])
        out_lines.append(f"上海Au99.99金价：{gold_price}  日期:{gold_date}")
    except Exception as e:
        traceback.print_exc()
        out_lines.append("上海金价获取失败")

    res_text = "\n".join(out_lines)
    write_cache(cache_name,res_text)
    return res_text

def search(user_input:str)->str:
    city_list= [
    "襄阳", "谷城", "宣城", "合肥", "芜湖", "蚌埠", "淮南", "马鞍山", "黄山",
    "北京", "上海", "天津", "重庆",
    "南京", "苏州", "无锡", "常州", "徐州", "扬州", "杭州", "宁波", "温州", "嘉兴",
    "广州", "深圳", "佛山", "东莞", "珠海", "汕头",
    "成都", "绵阳", "西安", "宝鸡", "武汉", "长沙", "郑州", "洛阳","大连","沈阳",
    "济南", "青岛", "烟台", "石家庄", "保定", "唐山",
    "福州", "厦门", "泉州", "南宁", "桂林", "昆明",
    "贵阳", "兰州", "西宁", "银川", "乌鲁木齐", "呼和浩特", "长春", "哈尔滨"
    ]
    target_cities = [city for city in city_list if city in user_input]
    if len(target_cities)>5:
        return "单次查询不要多于5个城市"
    weather_words = ["天气", "下雨", "气温", "热不热", "冷不冷", "带伞", "刮风"]
    news_words = ["热点", "热搜", "新闻", "最近大事", "知乎热榜"]
    money_words = ["汇率", "美元", "金价", "油价", "人民币"]
    if any(word in user_input for word in weather_words):
        out = ""
        for city in target_cities:
            out += weather(city) + "\n" + "-"*30 + "\n"
        if out.strip():
            return out.strip()
        return "请明确城市名称"
    elif any(word in user_input for word in news_words):
        return hot_news()+"\n\n"
    elif any(word in user_input for word in money_words):
        return money()+"\n\n"
    else:
        return "无时效性实时资讯，仅使用本地知识库与模型原生知识作答"