import re, numpy as np
txt=open(r'D:\FPGA2026_PRJ\zynq_ai_accel\board\mnist_model.h',encoding='latin-1').read()
def pa(n,d=np.int8):
    m=re.search(n+r'\s*\[\d+\]\s*=\s*\{([^}]*)\}',txt,re.S)
    return np.array([int(x) for x in re.findall(r'-?\d+',m.group(1))],dtype=d)
img=pa('TEST_IMG',np.uint8).astype(np.int8).astype(np.int32).reshape(28,28)
W1=pa('W1').astype(np.int32); W2=pa('W2').astype(np.int32)
def convpool(x, W, inc, outc, P, KW=3):
    IH=x.shape[1]; OH=(IH-KW+1)//P; W=W.reshape(outc,inc,KW,KW)
    out=np.zeros((outc,OH,OH),dtype=np.int8)
    for oc in range(outc):
        for py in range(OH):
            for px in range(OH):
                m=0
                for sy in range(P):
                    for sx in range(P):
                        oy=py*P+sy; ox=px*P+sx; acc=0
                        for ic in range(inc):
                            for ky in range(KW):
                                for kx in range(KW):
                                    acc+=x[ic,oy+ky,ox+kx]*W[oc,ic,ky,kx]
                        v=np.int8(acc>>8 if (acc>>8)<128 else (acc>>8)-256)
                        if v>m: m=v
                out[oc,py,px]=m
    return out
fb1=convpool(img[None,:,:],W1,1,8,2).astype(np.int8)
fb2=convpool(fb1.astype(np.int32),W2,8,16,2).astype(np.int8)
def c(nm, vals):
    lines=['// %s[%d]'%(nm,len(vals))]
    for i in range(0,len(vals),12):
        lines.append('    '+', '.join(str(int(v)) for v in vals[i:i+12])+',')
    return ('static const signed char '+nm+'[' + str(len(vals)) + '] = {\n'+'\n'.join(lines)+'\n};')
h = '// auto conv2 test vector\n#ifndef CONV2_TEST_H\n#define CONV2_TEST_H\n'
h += c('fb1', fb1.flatten()) + '\n'
h += c('W2', W2.flatten()) + '\n'
h += c('EXP', fb2.flatten()) + '\n'
h += '#endif\n'
open(r'D:\FPGA2026_PRJ\zynq_ai_accel\src\hls\conv2_test.h','w').write(h)
print('wrote', len(h),'bytes; fb1',len(fb1.flatten()),'W2',len(W2.flatten()),'EXP',len(fb2.flatten()))
print('EXP ch15 row2:', fb2[15,2].tolist())
