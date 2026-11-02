#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
weather.py —— 天气取数（给首页天气卡用）

为什么用 wttr.in：
  · 免 API key，支持 **http**（我们板子上 https 的 CA 校验过不去：
    `CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate`）
  · 返回 JSON，字段够用

设计要点：
  · **绝不阻塞 UI**：抓取放在后台线程，首页只读缓存
  · **离线降级**：抓不到就继续用上一次的缓存（并标出是几小时前的）
  · 缓存落盘 `/home/zynq/.weather.json`，重启不丢
  · 城市可改：`/home/zynq/.weather_city` 写城市名（中文/拼音/英文都行）
"""
import json
import os
import re
import threading
import time
import urllib.request

CACHE = "/home/zynq/.weather.json"
CITYFILE = "/home/zynq/.weather_city"
EVERY = 1800          # 正常 30 分钟刷一次
RETRY_FAIL = 300      # 失败后 5 分钟再试
TIMEOUT = 15

# wttr.in 的 lang=zh 实际上还是回英文，所以中文自己映射
_ZH = [
    ("thunder", "雷阵雨", "storm"),
    ("blizzard", "暴雪", "snow"),
    ("snow", "雪", "snow"),
    ("sleet", "雨夹雪", "sleet"),
    ("heavy rain", "大雨", "rain"),
    ("moderate rain", "中雨", "rain"),
    ("light rain", "小雨", "rain"),
    ("drizzle", "毛毛雨", "rain"),
    ("rain", "雨", "rain"),
    ("shower", "阵雨", "rain"),
    ("freezing", "冻雨", "sleet"),
    ("fog", "雾", "fog"),
    ("mist", "薄雾", "fog"),
    ("overcast", "阴", "cloud"),
    ("cloudy", "多云", "cloud"),
    ("cloud", "多云", "cloud"),
    ("clear", "晴", "sun"),
    ("sunny", "晴", "sun"),
]


# wttr.in 的 nearest_area 只回英文城市名，常见城市映射回中文
_CITY_ZH = {
    "beijing": "北京", "shanghai": "上海", "guangzhou": "广州", "shenzhen": "深圳",
    "chengdu": "成都", "hangzhou": "杭州", "wuhan": "武汉", "xian": "西安",
    "nanjing": "南京", "tianjin": "天津", "suzhou": "苏州", "chongqing": "重庆",
    "changsha": "长沙", "zhengzhou": "郑州", "qingdao": "青岛", "dalian": "大连",
    "xiamen": "厦门", "fuzhou": "福州", "hefei": "合肥", "jinan": "济南",
    "kunming": "昆明", "harbin": "哈尔滨", "shenyang": "沈阳", "taiyuan": "太原",
    "shijiazhuang": "石家庄", "nanchang": "南昌", "guiyang": "贵阳", "lanzhou": "兰州",
    "urumqi": "乌鲁木齐", "haikou": "海口", "nanning": "南宁", "hohhot": "呼和浩特",
    "yinchuan": "银川", "xining": "西宁", "lhasa": "拉萨", "wuxi": "无锡",
    "ningbo": "宁波", "wenzhou": "温州", "foshan": "佛山", "dongguan": "东莞",
}


def _city_zh(name, asked):
    """城市名转中文: 先查表; 查不到就用用户自己填的那个(通常已经是中文)"""
    if not name:
        return asked
    z = _CITY_ZH.get(name.strip().lower())
    if z:
        return z
    # 回的是英文, 而用户填的是中文 -> 相信用户
    if name.isascii() and asked and not asked.isascii():
        return asked
    return name


def _zh(desc):
    d = (desc or "").lower()
    for k, zh, kind in _ZH:
        if k in d:
            return zh, kind
    return (desc or "—"), "cloud"


class Weather(object):
    def __init__(self):
        self.city = "北京"
        self.data = None      # {temp,text,kind,city,hi,lo,hum,ts,dbm}
        self.err = ""
        self._busy = False
        self._last_ok = 0.0
        self._last_try = 0.0
        self._lock = threading.Lock()
        self._load_city()
        self.load_cache()

    # ---------- 配置 / 缓存 ----------
    def _load_city(self):
        try:
            c = open(CITYFILE).read().strip()
            if c:
                self.city = c
        except Exception:
            pass

    def set_city(self, c):
        self.city = (c or "").strip() or "北京"
        try:
            with open(CITYFILE, "w") as f:
                f.write(self.city)
        except Exception:
            pass
        self.refresh(force=True)

    def load_cache(self):
        try:
            d = json.load(open(CACHE))
            if isinstance(d, dict) and "temp" in d:
                self.data = d
                self._last_ok = float(d.get("ts", 0))
                return True
        except Exception:
            pass
        return False

    def _save_cache(self):
        try:
            with open(CACHE, "w") as f:
                json.dump(self.data, f, ensure_ascii=False)
        except Exception:
            pass

    # ---------- 抓取（后台线程） ----------
    def _fetch(self):
        try:
            url = ("http://wttr.in/%s?format=j1"
                   % urllib.request.quote(self.city.encode("utf-8")))
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68"})
            raw = urllib.request.urlopen(req, timeout=TIMEOUT).read()
            d = json.loads(raw.decode("utf-8", "replace"))
            cc = d["current_condition"][0]
            w0 = d["weather"][0]
            desc = ""
            try:
                desc = cc["weatherDesc"][0]["value"]
            except Exception:
                pass
            text, kind = _zh(desc)
            city = self.city
            try:
                na = d["nearest_area"][0]
                city = _city_zh(na["areaName"][0]["value"], self.city)
            except Exception:
                pass
            out = {
                "temp": int(float(cc.get("temp_C", 0))),
                "feel": int(float(cc.get("FeelsLikeC", cc.get("temp_C", 0)))),
                "text": text,
                "kind": kind,
                "desc": desc,
                "city": city,
                "hi": int(float(w0.get("maxtempC", 0))),
                "lo": int(float(w0.get("mintempC", 0))),
                "hum": int(float(cc.get("humidity", 0))),
                "wind": "%s %skm/h" % (cc.get("winddir16Point", ""),
                                       cc.get("windspeedKmph", "")),
                "ts": time.time(),
            }
            with self._lock:
                self.data = out
                self.err = ""
                self._last_ok = out["ts"]
            self._save_cache()
            print("[weather] %s %d°C %s (高%d 低%d)" % (city, out["temp"], text,
                                                        out["hi"], out["lo"]))
            return True
        except Exception as e:
            self.err = "%s: %s" % (type(e).__name__, e)
            print("[weather] 抓取失败: %s" % self.err)
            return False
        finally:
            self._busy = False

    def refresh(self, force=False, blocking=False):
        """触发一次刷新；默认放到后台线程，不阻塞界面"""
        now = time.time()
        if self._busy:
            return False
        ok_age = now - self._last_ok
        try_age = now - self._last_try
        if not force:
            if self._last_ok and ok_age < EVERY:
                return False
            if not self._last_ok and try_age < 60:
                return False
            if self._last_ok == 0 and try_age < RETRY_FAIL and self.err:
                return False
        self._busy = True
        self._last_try = now
        if blocking:
            return self._fetch()
        t = threading.Thread(target=self._fetch, name="weather", daemon=True)
        t.start()
        return True

    def get(self):
        """给界面用：返回 dict 或 None（离线时回上一次的缓存）"""
        with self._lock:
            return dict(self.data) if self.data else None

    def age_str(self):
        if not self._last_ok:
            return ""
        s = int(time.time() - self._last_ok)
        if s < 90:
            return "刚刚更新"
        if s < 3600:
            return "%d 分钟前" % (s // 60)
        if s < 86400:
            return "%d 小时前" % (s // 3600)
        return "%d 天前" % (s // 86400)


_W = None


def get_weather():
    global _W
    if _W is None:
        _W = Weather()
    return _W


if __name__ == "__main__":
    import sys
    w = get_weather()
    print("城市:", w.city)
    if len(sys.argv) > 1:
        w.set_city(sys.argv[1])
    ok = w.refresh(force=True, blocking=True)
    print("结果:", json.dumps(w.get(), ensure_ascii=False, indent=2))
    print("err:", w.err, " 时间:", w.age_str())
