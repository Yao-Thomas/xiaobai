import re,numpy as np
txt=open(r'D:\FPGA2026_PRJ\zynq_ai_accel\board\mnist_model.h',encoding='latin-1').read()
def pa(n,d=np.int8):
    m=re.search(n+r'\s*\[\d+\]\s*=\s*\{([^}]*)\}',txt,re.S); return np.array([int(x) for x in re.findall(r'-?\d+',m.group(1))],dtype=d)
imgu=pa('TEST_IMG',np.uint8).astype(np.int64)   # uint8
W1=pa('W1').astype(np.int64); W2=pa('W2').astype(np.int64); WF=pa('WF').astype(np.int64)
# input int8 = u8-128
xin=(imgu.reshape(28,28)-128).astype(np.int64)

def conv8q(x, W, inc, outc, MFQ):
    KW=3; OH=x.shape[1]-KW+1; W=W.reshape(outc,inc,KW,KW); o=np.zeros((outc,OH,OH),dtype=np.int64)
    for oc in range(outc):
        for oy in range(OH):
            for ox in range(OH):
                acc=int(sum(x[ic,oy+ky,ox+kx]*int(W[oc,ic,ky,kx]) for ic in range(inc) for ky in range(3) for kx in range(3)))
                q=(acc*MFQ)>>16
                if q<0:q=0
                if q>127:q=127
                o[oc,oy,ox]=q
    return o
def pool8(f):
    OH=f.shape[1]//2; o=np.zeros((f.shape[0],OH,OH),dtype=np.int64)
    for oc in range(f.shape[0]):
        for py in range(OH):
            for px in range(OH):
                o[oc,py,px]=max(int(f[oc,py*2+s0,px*2+s1]) for s0 in range(2) for s1 in range(2))
    return o

for MFQ in [119,115,120,108]:
    x1=conv8q(xin[None,:,:],W1,1,8,MFQ); p1=pool8(x1)
    x2=conv8q(p1,W2,8,16,MFQ); p2=pool8(x2)
    xf=p2.flatten().astype(np.int64)
    lg=np.array([(int((xf*WF[oc*400:(oc+1)*400]).sum())*MFQ)>>16 for oc in range(10)],dtype=np.int64)
    print('MFQ=%d logits'%MFQ, lg.tolist(), '-> argmax', int(np.argmax(lg)))
