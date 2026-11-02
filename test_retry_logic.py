# 模拟 grab_energy 的重试逻辑（不碰硬件）
import random
class T:
    RETRY = 3
    def __init__(self, zero_rate): 
        self.z = zero_rate; self.STATS={"zero":0,"grabs":0,"retried":0}
    def one_grab(self):
        self.STATS["grabs"] += 1
        if random.random() < self.z:
            self.STATS["zero"] += 1
            return [0.0]*6
        return [100.0, 50, 30, 20, 10, 5]
    def grab_energy(self):
        zeros = 0
        for _ in range(self.RETRY):
            e = self.one_grab()
            if max(e) > 0:
                if zeros: self.STATS["retried"] += 1
                return e, zeros
            zeros += 1
        return [0.0]*6, zeros

print("  %-12s %-12s %-14s %-12s" % ("全零概率", "总采集", "全零次数", "最终拿到数据"))
print("  " + "-"*56)
for zr in (0.0, 0.2, 0.5, 0.8, 0.95):
    random.seed(42)
    t = T(zr)
    good = 0
    for _ in range(200):
        e, z = t.grab_energy()
        if max(e) > 0: good += 1
    print("  %-12.2f %-12d %-14d %d/200 (%.0f%%)" % (zr, t.STATS["grabs"], t.STATS["zero"], good, good/2.0))
print()
print("  读法：单次全零概率 80% 时，3 次重试仍有 1-(0.8^3)=48.8% 会全零；")
print("        所以 RETRY=3 对高故障率不够，实验里要能看出这个数。")