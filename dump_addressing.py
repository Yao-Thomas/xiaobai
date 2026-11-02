import json, re

BD = r"D:\ubuntu_iso\atk2018\atk2018.srcs\sources_1\bd\system\system.bd"
raw = open(BD, "r", encoding="utf-8", errors="replace").read()
j = json.loads(raw[re.search(r"\{", raw).start():])
d = j["design"]

print("=== addressing 段 ===")
ad = d.get("addressing", {})
print("  顶层键:", list(ad.keys())[:10])

# 找 gpu 相关
s = json.dumps(ad, ensure_ascii=False)
for key in ("gpu_0", "hp3_merge"):
    print("\n--- %s 出现 %d 次 ---" % (key, s.count(key)))

# 打印所有 master 的 address_space
for name, sp in ad.items():
    if isinstance(sp, dict):
        segs = []
        for k, v in sp.items():
            if isinstance(v, dict):
                for seg, val in v.items():
                    if isinstance(val, dict):
                        segs.append("%s/%s off=%s" % (k, seg, val.get("offset", "?")))
        if segs:
            print("\n[%s]" % name)
            for x in segs[:14]:
                print("   ", x)
