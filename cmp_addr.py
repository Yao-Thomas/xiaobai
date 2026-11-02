import json, re

BD = r"D:\ubuntu_iso\atk2018\atk2018.srcs\sources_1\bd\system\system.bd"
raw = open(BD, "r", encoding="utf-8", errors="replace").read()
j = json.loads(raw[re.search(r"\{", raw).start():])
ad = j["design"]["addressing"]

print("=" * 70)
print(" 对比: 能工作的 audio DMA  vs  我们的 gpu_0")
print("=" * 70)

for key in ("/audio/audio_formatter", "/gpu_0"):
    print("")
    print("### %s" % key)
    blk = ad.get(key)
    if blk is None:
        print("   (不存在!)")
        continue
    print(json.dumps(blk, indent=2, ensure_ascii=False)[:2000])

print("")
print("=" * 70)
print(" processing_system7_0/Data 下有没有 HP3 的段")
print("=" * 70)
ps = ad.get("/processing_system7_0", {})
sp = ps.get("address_spaces", {}).get("Data", {})
for k, v in sp.items():
    if "HP3" in k or "HP" in k:
        print("   %s" % k)
