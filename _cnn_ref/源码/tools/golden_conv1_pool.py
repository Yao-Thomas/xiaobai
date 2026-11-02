import numpy as np, re
H = r"D:\FPGA2026_PRJ\zynq_ai_accel\board\mnist_model.h"
txt = open(H, encoding="latin-1").read()
def pa(n,d=np.int8):
    m=re.search(n+r"\s*\[\d+\]\s*=\s*\{([^}]*)\}",txt,re.S)
    return np.array([int(x) for x in re.findall(r"-?\d+",m.group(1))],dtype=d)
img=pa("TEST_IMG",np.uint8).astype(np.int8).astype(np.int32).reshape(28,28)
W1=pa("W1").astype(np.int32).reshape(8,3,3)   # [oc][kh][kw] (in=1)
IH=IW=28; KH=KW=3; P=2
OH=(IH-KH+1)//P; OW=(IW-KW+1)//P
# conv (no pool first) -> 26x26x8
C26=IH-KH+1
conv=np.zeros((8,C26,C26),dtype=np.int32)
for oc in range(8):
    for oy in range(C26):
        for ox in range(C26):
            conv[oc,oy,ox]=sum(img[oy+ky,ox+kx]*W1[oc,ky,kx] for ky in range(3) for kx in range(3))
# 与内核一致：先把 conv>>8 按 int8(二补数)回绕，再 ReLU(max0)，再 2x2 池化
conv8=(conv>>8).astype(np.int8).astype(np.int32)
relu=np.maximum(conv8,0)
pooled=np.zeros((8,OH,OW),dtype=np.int8)
for oc in range(8):
    for py in range(OH):
        for px in range(OW):
            pooled[oc,py,px]=relu[oc,py*2:py*2+2,px*2:px*2+2].max()
print("OUT_CH=8 OH=%d OW=%d -> size %d"%(OH,OW,8*OH*OW))
print("pooled flatten row0 (channel0, py0):", pooled[0,0].tolist())
print("channel0 row 6:", pooled[0,6].tolist())
print("channel1 row 6:", pooled[1,6].tolist())
print("channel7 row 6:", pooled[7,6].tolist())
print("min,max pooled:", pooled.min(), pooled.max())
