import numpy as np, re, os

H = r"D:\FPGA2026_PRJ\zynq_ai_accel\board\mnist_model.h"
txt = open(H, encoding="utf-8", errors="replace").read()

def parse_array(name, dtype=np.int8):
    pat = name + r"\s*\[\d+\]\s*=\s*\{([^}]*)\}"
    m = re.search(pat, txt, re.S)
    if not m:
        m = re.search(rf"{name}\s*\[\s*\]\s*=\s*\{{(.*?)\}}", txt, re.S)
    body = m.group(1)
    vals = [int(x) for x in re.findall(r"-?\d+", body)]
    return np.array(vals, dtype=dtype) if vals else None

def parse_val(name):
    m = re.search(rf"\b{name}\b\s*=\s*([-\d.eE+]+)", txt)
    return float(m.group(1)) if m else None

W1 = parse_array("W1")
TEST_IMG = parse_array("TEST_IMG", np.uint8)
W1_SCALE = parse_val("W1_SCALE")
print("W1 len=%d  TEST_IMG len=%d  W1_SCALE=%s" % (len(W1), len(TEST_IMG), W1_SCALE))

IH=IW=28; KH=KW=3
# 与 C 主程序一致：uint8(0..255) 按有符号 int8 字节解释
img = TEST_IMG.astype(np.int8).astype(np.int32).reshape(IH,IW)
# conv1 output channel 0 weights = W1[0:9]
w = W1[0:9].reshape(KH,KW).astype(np.int32)
OH=IH-KH+1; OW=IW-KW+1
out=np.zeros((OH,OW),dtype=np.int32)
for oy in range(OH):
    for ox in range(OW):
        acc=0
        for ky in range(KH):
            for kx in range(KW):
                acc += img[oy+ky,ox+kx]*w[ky,kx]
        out[oy,ox]=acc
# quantized int8 = acc >> 8 (matches HLS)
q = (out>>8).astype(np.int8)
print("golden conv1[ch0] int8, first row (26 values):")
print(q[0].tolist())
print("golden conv1[ch0] int8, first 5 cols x 5 rows:")
print(q[:5,:5].tolist())
print("min,max of q:", q.min(), q.max())
