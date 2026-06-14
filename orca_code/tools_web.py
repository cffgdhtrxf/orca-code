
import hashlib as _hashlib
import json
import logging
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

from orca_code.config import (
    SCRIPT_DIR,
    TAVILY_API_KEY,
    TERM_WIDTH,
    USER_CITY,
    console,
    search_cache,
)
from orca_code.security import _TEST_LOCATION_HASH, is_safe_url

"""orca_code.tools_web — Web fetch, search, weather, location."""


def web_fetch(url: str) -> str:
    safe, reason = is_safe_url(url)
    if not safe:
        return f"错误: {reason}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read().decode("utf-8", errors="replace")
            return data[:10000] if len(data) > 10000 else data
    except Exception as e:
        return f"错误: {e}"
def read_webpage(url: str) -> str:
    safe, reason = is_safe_url(url)
    if not safe:
        return f"错误: {reason}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"错误: 读取失败 - {e}"

    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "head", "header", "nav", "footer", "iframe", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
    except ImportError:
        for tag in ("script", "style", "head", "header", "nav", "footer", "iframe", "noscript"):
            html = re.sub(rf'<{tag}[^>]*>.*?</{tag}>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', '\n', html)

    for old, new in [('&nbsp;', ' '), ('&lt;', '<'), ('&gt;', '>'), ('&amp;', '&'), ('&quot;', '"'), ("&#39;", "'")]:
        text = text.replace(old, new)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    if len(text) > 8000:
        text = text[:8000] + "\n\n... (已截断)"
    return text if text else "未能提取到有效文本内容"
def _optimize_search_query(query: str) -> list[str]:
    results = []
    if any(kw in query for kw in ("天气", "weather", "气温", "温度")):
        for pat in [r'([一-鿿a-zA-Z\s]+?)(?:天气|气温|温度|预报|weather)']:
            m = re.search(pat, query)
            if m:
                loc = m.group(1).strip()
                if len(loc) > 1:
                    results.extend([f"{loc} 今日天气", f"{loc} weather today"])
                break
    if query not in results:
        results.append(query)
    return results[:3]
def _score_results(results: list[dict], query: str) -> None:
    auth = {".gov.cn": 15, ".edu.cn": 12, "weather.com.cn": 15, "bbc.com": 10,
            "reuters.com": 10, "accuweather.com": 12, "weather.com": 12}
    qkw = set(query.lower().split())
    for r in results:
        href = r.get("href", "").lower()
        for d, pts in auth.items():
            if d in href:
                r["score"] = r.get("score", 0) + pts
                break
        title = r.get("title", "").lower()
        r["score"] = r.get("score", 0) + len(qkw & set(title.split())) * 2
def _search_with_tavily(query: str, max_results: int = 10, topic: str = "general", days: int = 0) -> list[dict]:
    ck = f"tavily:{query}:{max_results}:{topic}:{days}"
    cached = search_cache.get(ck)
    if cached is not None:
        return cached
    if not TAVILY_API_KEY:
        return [{"error": "未配置 tavily_api_key"}]
    body = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "advanced",
        "include_answer": True,
        "include_raw_content": True,
        "max_results": max_results,
        "topic": topic,
    }
    if days > 0:
        body["days"] = days
    try:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            "https://api.tavily.com/search", data=data,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            r = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as e:
        return [{"error": str(e)}]
    results = []
    for item in r.get("results", []):
        content = item.get("raw_content") or item.get("content", "")
        if content and len(content) > 2000:
            content = content[:2000] + "..."
        results.append({
            "title": item.get("title", ""),
            "body": content or item.get("content", ""),
            "href": item.get("url", ""),
            "score": item.get("score", 0),
            "source": "tavily",
        })
    _score_results(results, query)
    results.sort(key=lambda x: x["score"], reverse=True)
    seen = set()
    unique = []
    for x in results:
        if x["href"] not in seen:
            seen.add(x["href"])
            unique.append(x)
    final = unique[:max_results]
    search_cache[ck] = final
    return final
def _ddg_fallback(query: str) -> str:
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"错误: 搜索失败 - {e}"
    results = []
    for m in re.finditer(
        r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
        r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL
    ):
        u = urllib.parse.unquote(m.group(1))
        if "uddg=" in u:
            u = urllib.parse.parse_qs(urllib.parse.urlparse(u).query).get("uddg", [u])[0]
        t = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        s = re.sub(r'<[^>]+>', '', m.group(3)).strip()
        if t:
            results.append(f"{len(results) + 1}. {t}\n    {u}\n    {s}")
        if len(results) >= 10:
            break
    return "\n\n".join(results) if results else f"未找到与 '{query}' 相关的结果"
def web_search(query: str, days: int = 0, topic: str = "general") -> str:
    queries = _optimize_search_query(query)
    for q in queries:
        if not TAVILY_API_KEY:
            break
        tavily_results = _search_with_tavily(q, topic=topic, days=days)
        if not (len(tavily_results) == 1 and "error" in tavily_results[0]):
            lines = [f"{i + 1}. {r['title']}\n    {r['href']}\n    {r['body']}"
                     for i, r in enumerate(tavily_results)]
            return "\n\n".join(lines) if lines else f"未找到与 '{query}' 相关的结果"
        console.print(f"  [dim]Tavily 不可用: {tavily_results[0]['error']}，降级到 DDG[/dim]")
    return _ddg_fallback(query)
def get_weather(location: str) -> str:
    try:
        if TERM_WIDTH < 100:
            url = f"https://wttr.in/{urllib.parse.quote(location)}?lang=zh&format=2"
        else:
            url = f"https://wttr.in/{urllib.parse.quote(location)}?lang=zh"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace").strip()
        lines = []
        for line in raw.split("\n"):
            if any(s in line.lower() for s in ("igor_chubin", "igor@chubin", "follow @")):
                continue
            if len(line) > TERM_WIDTH - 2:
                line = line[:TERM_WIDTH - 2]
            lines.append(line)
        return "\n".join(lines)
    except Exception as e:
        return f"错误: 天气查询失败 - {e}"
def _get_system_location() -> dict | None:
    if sys.platform != "win32":
        return None
    script = SCRIPT_DIR / "test_location.ps1"
    if not script.exists():
        return None
    # [SECURITY] Verify PS1 script integrity before executing with -ExecutionPolicy Bypass
    try:
        actual_hash = _hashlib.sha256(script.read_bytes()).hexdigest()
        expected_hash = os.environ.get("PS1_LOCATION_HASH", _TEST_LOCATION_HASH)
        if actual_hash != expected_hash:
            logging.error("PS1 integrity check FAILED — expected %s, got %s", expected_hash[:16], actual_hash[:16])
            return {"error": "位置服务脚本校验失败，可能被篡改。请重新部署 test_location.ps1"}
    except Exception:
        return {"error": "位置服务脚本读取失败"}
    try:
        r = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            capture_output=True, text=True, timeout=15, encoding="utf-8", errors="replace"
        )
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout.strip())
            if "error" not in data:
                lat, lon = data.get("latitude", 0), data.get("longitude", 0)
                if lat and lon and lat != 0 and lon != 0:
                    city, region = _match_city_by_coords(lat, lon)
                    return {"city": city, "region": region, "country": "中国",
                            "lat": lat, "lon": lon, "source": "system_location"}
            else:
                # Store the error for better diagnostics
                return {"error": data["error"]}
    except subprocess.TimeoutExpired:
        return None
    except Exception as e:
        logging.debug("_get_system_location unexpected error: %s", e)
    return None
def _match_city_by_coords(lat: float, lon: float) -> tuple[str, str]:
    cities = [
        (23.0, 23.5, 113.0, 114.0, "广州", "广东"),
        (22.5, 22.8, 114.0, 114.2, "深圳", "广东"),
        (23.5, 23.8, 116.5, 116.8, "潮州", "广东"),
        (23.3, 23.5, 113.5, 113.7, "汕头", "广东"),
        (23.1, 23.3, 113.1, 113.3, "佛山", "广东"),
        (23.0, 23.2, 114.3, 114.5, "惠州", "广东"),
        (23.3, 23.5, 113.7, 113.9, "东莞", "广东"),
        (22.5, 22.7, 113.3, 113.5, "中山", "广东"),
        (22.0, 22.3, 113.5, 113.8, "珠海", "广东"),
        (23.7, 23.9, 113.5, 113.7, "江门", "广东"),
        (21.8, 22.0, 110.3, 110.5, "湛江", "广东"),
        (21.6, 21.8, 110.9, 111.1, "茂名", "广东"),
        (23.7, 23.9, 112.3, 112.5, "韶关", "广东"),
        (24.2, 24.4, 116.1, 116.3, "梅州", "广东"),
        (23.3, 23.5, 115.3, 115.5, "汕尾", "广东"),
        (23.7, 23.9, 114.6, 114.8, "河源", "广东"),
        (21.8, 22.0, 111.9, 112.1, "阳江", "广东"),
        (23.6, 23.8, 116.0, 116.2, "揭阳", "广东"),
        (22.9, 23.1, 112.0, 112.2, "云浮", "广东"),
        (23.7, 23.9, 113.0, 113.2, "清远", "广东"),
        (23.3, 23.5, 112.0, 112.2, "肇庆", "广东"),
        (39.8, 40.0, 116.3, 116.5, "北京", "北京"),
        (31.1, 31.3, 121.4, 121.5, "上海", "上海"),
        (39.0, 39.2, 117.1, 117.3, "天津", "天津"),
        (29.5, 29.7, 106.5, 106.6, "重庆", "重庆"),
        (30.2, 30.4, 120.1, 120.3, "杭州", "浙江"),
        (29.8, 30.0, 121.5, 121.7, "宁波", "浙江"),
        (27.9, 28.1, 120.6, 120.8, "温州", "浙江"),
        (32.0, 32.2, 118.7, 118.9, "南京", "江苏"),
        (31.2, 31.4, 120.5, 120.7, "苏州", "江苏"),
        (26.0, 26.2, 119.2, 119.4, "福州", "福建"),
        (24.4, 24.6, 118.0, 118.2, "厦门", "福建"),
        (24.9, 25.1, 118.5, 118.7, "泉州", "福建"),
        (36.6, 36.8, 117.0, 117.2, "济南", "山东"),
        (36.0, 36.2, 120.3, 120.5, "青岛", "山东"),
        (37.4, 37.6, 121.3, 121.5, "烟台", "山东"),
        (37.5, 37.7, 122.1, 122.3, "威海", "山东"),
        (38.0, 38.2, 114.4, 114.6, "石家庄", "河北"),
        (39.9, 40.1, 119.5, 119.7, "秦皇岛", "河北"),
        (34.7, 34.9, 113.6, 113.8, "郑州", "河南"),
        (34.6, 34.8, 112.4, 112.6, "洛阳", "河南"),
        (30.5, 30.7, 114.2, 114.4, "武汉", "湖北"),
        (28.2, 28.4, 112.9, 113.1, "长沙", "湖南"),
        (30.6, 30.8, 104.0, 104.2, "成都", "四川"),
        (25.0, 25.2, 102.7, 102.9, "昆明", "云南"),
        (26.6, 26.8, 106.7, 106.9, "贵阳", "贵州"),
        (22.8, 23.0, 108.3, 108.5, "南宁", "广西"),
        (28.6, 28.8, 115.9, 116.1, "南昌", "江西"),
        (31.8, 32.0, 117.2, 117.4, "合肥", "安徽"),
        (45.7, 45.9, 126.6, 126.8, "哈尔滨", "黑龙江"),
        (43.8, 44.0, 125.3, 125.5, "长春", "吉林"),
        (41.7, 41.9, 123.4, 123.6, "沈阳", "辽宁"),
        (38.9, 39.1, 121.6, 121.8, "大连", "辽宁"),
        (34.3, 34.5, 108.9, 109.1, "西安", "陕西"),
        (36.0, 36.2, 103.8, 104.0, "兰州", "甘肃"),
        (36.6, 36.8, 101.7, 101.9, "西宁", "青海"),
        (38.4, 38.6, 106.2, 106.4, "银川", "宁夏"),
        (43.8, 44.0, 87.6, 87.8, "乌鲁木齐", "新疆"),
        (29.6, 29.8, 91.1, 91.3, "拉萨", "西藏"),
        (40.8, 41.0, 111.7, 111.9, "呼和浩特", "内蒙古"),
        (37.8, 38.0, 112.5, 112.7, "太原", "山西"),
        (19.9, 20.1, 110.3, 110.5, "海口", "海南"),
        (18.2, 18.4, 109.5, 109.7, "三亚", "海南"),
        (22.3, 22.5, 113.5, 113.7, "澳门", "澳门"),
        (22.2, 22.4, 114.1, 114.3, "香港", "香港"),
    ]
    for lat_min, lat_max, lon_min, lon_max, city, region in cities:
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return city, region
    return "未知", "未知"
def get_location() -> str:
    if USER_CITY:
        return f"城市: {USER_CITY}（手动设置）"
    sys_loc = _get_system_location()
    if sys_loc:
        if "error" in sys_loc:
            return (f"Windows 位置服务不可用: {sys_loc['error']}\n"
                    f"解决方法: 1) 开启 Windows 设置 > 隐私 > 位置\n"
                    f"         2) 或在 config.json 中设置 user_city 手动指定城市")
        return (f"城市: {sys_loc['city']}\n省份: {sys_loc['region']}\n"
                f"国家: {sys_loc['country']}\n坐标: {sys_loc['lat']},{sys_loc['lon']}\n"
                f"来源: Windows 系统定位")
    return "无法获取位置。请在 config.json 中设置 user_city 手动指定城市，或开启 Windows 位置服务"
