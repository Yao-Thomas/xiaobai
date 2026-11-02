# 复刻 one_matrix 的判定逻辑，喂全零/正常数据看命中怎么算
FREQS = [495.3, 646.0, 990.5, 1292.0, 1507.3, 2002.6]
def judge(rows_e, f0):
    e = rows_e
    valid = max(e) > 0
    top = e.index(max(e)) if valid else -1
    return bool(valid and top == FREQS.index(f0)), top

print("  场景 A: 采到 f0=495.3 的纯音")
e = [100.0, 5, 3, 2, 1, 1]
ok, top = judge(e, 495.3)
print("    valid=True top=%s(%.1f) ok=%s   <- 期望 True" % (top, FREQS[top], ok))

print("  场景 B: 全零（故障B），且 f0 正好是 freqs[0]=495.3")
e = [0.0]*6
ok, top = judge(e, 495.3)
print("    valid=False top=%s ok=%s   <- 期望 **False**（旧代码会给 True）" % (top, ok))

print("  场景 C: 全零，f0=freqs[3]")
ok, top = judge([0.0]*6, 1292.0)
print("    valid=False top=%s ok=%s   <- 期望 False" % (top, ok))

print()
print("  旧代码（无 valid）在场景 B 下的结果：")
e=[0.0]*6
top = e.index(max(e))
print("    top=%s(%.1f) ok=%s   <- 假命中！" % (top, FREQS[top], top==FREQS.index(495.3)))