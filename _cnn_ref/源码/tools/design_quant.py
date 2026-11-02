import re,numpy as np
txt=open(r'D:\FPGA2026_PRJ\zynq_ai_accel\board\mnist_model.h',encoding='latin-1').read()
def pa(n,d=np.int8):
    m=re.search(n+r'\s*\[\d+\]\s*=\s*\{([^}]*)\}',txt,re.S); return np.array([int(x) for x in re.findall(r'-?\d+',m.group(1))],dtype=d)
def pf(n): return float(re.search(r'\b'+n+r'\b\s*=\s*([-0-9.eE+]+)',txt).group(1))
imgu=pa('TEST_IMG',np.uint8).astype(np.float64)
W1=pa('W1').astype(np.float64); B1=pa('B1').astype(np.float64)
W2=pa('W2').astype(np.float64); B2=pa('B2').astype(np.float64)
WF=pa('WF').astype(np.float64); BF=pa('BF').astype(np.float64)
sW1=pf('W1_SCALE'); sB1=pf('B1_SCALE'); sW2=pf('W2_SCALE'); sB2=pf('B2_SCALE'); sWF=pf('WF_SCALE'); sBF=pf('BF_SCALE')
x=imgu.reshape(28,28)-128.0  # input int8, scale 1.0

def conv(x,W,inc,outc):  # no pool, float conv
    KW=3; OH=x.shape[1]-KW+1; out=np.zeros((outc,OH,OH))
    W=W.reshape(outc,inc,KW,KW)
    for oc in range(outc):
        for oy in range(OH):
            for ox in range(OH):
                out[oc,oy,ox]=sum(x[ic,oy+ky,ox+kx]*W[oc,ic,ky,kx] for ic in range(inc) for ky in range(3) for kx in range(3))
    return out
def pool(f):  # 2x2 max
    OH=f.shape[1]//2; out=np.zeros((f.shape[0],OH,OH))
    for oc in range(f.shape[0]):
        for py in range(OH):
            for px in range(OH):
                out[oc,py,px]=f[oc,py*2:py*2+2,px*2:px*2+2].max()
    return out

# conv1 float (before quantize)
f1=conv(x[None,:,:],W1,1,8)*sW1 + B1[:,None,None]*sB1
print('x1_f (conv1+relu float) min/max:', f1.min(), f1.max())
# pools with relu
f1r=np.maximum(f1,0); p1f=pool(f1r)
# conv2 float
f2=conv(p1f,W2,8,16)*sW2 + B2[:,None,None]*sB2
print('x2_f (conv2+relu float) min/max:', f2.min(), f2.max())
f2r=np.maximum(f2,0); p2f=pool(f2r)
xf=p2f.flatten()
logits=np.array([(xf*WF[oc*400:(oc+1)*400]).sum()*sWF+(BF[oc]*sBF) for oc in range(10)])
print('float logits argmax:', int(np.argmax(logits)), 'logits', np.round(logits,2).tolist())

# ---- DESIGN S_x for int8 preservation ----
Sx1 = max(np.abs(f1r).max(),1e-9)/127.0
Sx2 = max(np.abs(f2r).max(),1e-9)/127.0
Sout = max(np.abs(logits).max(),1e-9)/127.0
print('\nS_x1=%.3e  S_x2=%.3e  Sout=%.3e'%(Sx1,Sx2,Sout))
# requant multipliers (as float, before fixed-point)
M1 = (1.0*sW1)/Sx1; M1b = B1*sB1/Sx1
M2 = (Sx1*sW2)/Sx2; M2b = B2*sB2/Sx2
M3 = (Sx2*sWF)/Sout; M3b = BF*sBF/Sout
print('M1=%.4f M1b~%.3f | M2=%.4f M2b~%.3f | M3=%.4f M3b~%.3f'%(M1,np.abs(M1b).max(),M2,np.abs(M2b).max(),M3,np.abs(M3b).max()))

# ---- verify int8 requant pipeline gives argmax 7 ----
def conv8(x8,W,intc,outc,M,Mb):  # int8 in, fixed-point requant
    KW=3; OH=x8.shape[1]-KW+1; W=W.reshape(outc,intc,KW,KW); out=np.zeros((outc,OH,OH),dtype=np.int32)
    for oc in range(outc):
        for oy in range(OH):
            for ox in range(OH):
                acc=sum(int(x8[ic,oy+ky,ox+kx])*int(W[oc,ic,ky,kx]) for ic in range(intc) for ky in range(3) for kx in range(3))
                out[oc,oy,ox]=int(np.round(acc*M + Mb[oc]))
    return out
def pool8(f):
    OH=f.shape[1]//2; out=np.zeros((f.shape[0],OH,OH),dtype=np.int32)
    for oc in range(f.shape[0]):
        for py in range(OH):
            for px in range(OH):
                out[oc,py,px]=max(int(f[oc,py*2+s0,px*2+s1]) for s0 in range(2) for s1 in range(2))
    return out
x1=conv8(x[None,:,:].astype(np.int32),W1,1,8,M1,M1b)
print('x1 int8 range after requant:', x1.min(), x1.max())
x1r=np.clip(x1,0,127); p1=pool8(x1r)
x2=conv8(p1,W2,8,16,M2,M2b); x2r=np.clip(x2,0,127); p2=pool8(x2r)
xf2=p2.flatten().astype(np.int64)
lg=np.array([np.round((xf2*WF[oc*400:(oc+1)*400]).sum()*M3 + M3b[oc]).astype(int) for oc in range(10)])
print('INT8 requant logits argmax:', int(np.argmax(lg)), 'logits', lg.tolist())
