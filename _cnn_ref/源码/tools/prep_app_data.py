import re, os
H = r"D:\FPGA2026_PRJ\zynq_ai_accel\board\mnist_model.h"
txt = open(H, encoding="latin-1").read()

def parse_array(name):
    pat = name + r"\s*\[\d+\]\s*=\s*\{([^}]*)\}"
    m = re.search(pat, txt, re.S)
    if not m:
        return []
    body = m.group(1)
    return [int(x) for x in re.findall(r"-?\d+", body)]

def parse_float(name):
    m = re.search(r"\b" + name + r"\b\s*=\s*([-0-9.eE+]+)", txt)
    return m.group(1) if m else "0.0"

names = ["TEST_IMG","W1","B1","W2","B2","WF","BF"]
data = {}
for n in names:
    data[n] = parse_array(n)
    print(f"{n}: len={len(data[n])}")
img=data["TEST_IMG"]; W1=data["W1"]; B1=data["B1"]; W2=data["W2"]; B2=data["B2"]; WF=data["WF"]; BF=data["BF"]
assert len(img)==784 and len(W1)==72 and len(B1)==8 and len(W2)==1152 and len(B2)==16 and len(WF)==4000 and len(BF)==10
scales = {k: parse_float(k+"_SCALE") for k in ["W1","B1","W2","B2","WF","BF"]}

def cbytes(vals, per=16):
    lines=[]
    for i in range(0,len(vals),per):
        lines.append("    " + ", ".join(str(v) for v in vals[i:i+per]) + ",")
    return "\n".join(lines)

T="unsigned char"; I="signed char"
out = """// auto-generated mnist_data.h (ASCII) from board/mnist_model.h
#ifndef MNIST_DATA_H
#define MNIST_DATA_H
// TEST_IMG: 28x28 handwritten digit, 0..255, label=7
static const NAMET TEST_IMG[784] = {
""" + cbytes(img) + """
};
static const int TEST_IMG_LABEL = 7;
// ---- Conv1 (1->8, 3x3) [out][in][kh][kw] ----
static const NAMEW W1[72] = {
""" + cbytes(W1) + """
};
static const NAMEW B1[8] = {
""" + cbytes(B1) + """
};
static const float W1_SCALE = """ + scales["W1"] + """;
static const float B1_SCALE = """ + scales["B1"] + """;
// ---- Conv2 (8->16, 3x3) [out][in][kh][kw] ----
static const NAMEW W2[1152] = {
""" + cbytes(W2) + """
};
static const NAMEW B2[16] = {
""" + cbytes(B2) + """
};
static const float W2_SCALE = """ + scales["W2"] + """;
static const float B2_SCALE = """ + scales["B2"] + """;
// ---- FC (400->10) [out][in] ----
static const NAMEW WF[4000] = {
""" + cbytes(WF) + """
};
static const NAMEW BF[10] = {
""" + cbytes(BF) + """
};
static const float WF_SCALE = """ + scales["WF"] + """;
static const float BF_SCALE = """ + scales["BF"] + """;
#endif
"""
out = out.replace("NAMET", T).replace("NAMEW", I)
dst = r"D:\FPGA2026_PRJ\zynq_ai_accel\src\ps_sw_cnn\mnist_data.h"
open(dst, "w", encoding="ascii").write(out)
print("wrote", dst, os.path.getsize(dst), "bytes")
