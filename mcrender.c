/*
 * mcrender.c —— 体素空间地形渲染器 (Voxel Space / Comanche 算法)
 *
 * 算法参考: https://github.com/s-macke/VoxelSpace  (MIT, s-macke)
 * 按官方的三条要点重写:
 *
 *  1) 【颜色图】而不是"高度→颜色"渐变
 *     官方原文: "a great advantage of the colormap is, that it already
 *     contains the shading and shadows. The Voxel Space engine just takes
 *     the color and doesn't have to compute illumination during the render
 *     process."
 *     => 我们在 init 时按【高度 + 坡向明暗 + 细节噪声】把每个格子的
 *        颜色索引烘焙好, 存进一张表; 渲染时只查一次表, 不算光照。
 *        这是"画面不像一坨色块"的关键。
 *
 *  2) 【平面投影】(水平半视角 45°), 不是角度投影
 *     屏幕第 i 列对应世界里从视点出发的直线, 方向 = forward + right*cx,
 *     cx = 2i/(W-1) - 1 ∈ [-1,1]。官方 pleft/pright 拉开的范围就是 ±z。
 *     (用 atan 做角度映射是柱面投影, 直线会弯、近处被拉扁。)
 *
 *  3) 高度和颜色【成对采样】
 *     我们把两者打包进一个 16bit 字 (高字节=高度, 低字节=颜色索引),
 *     一次内存访问拿到两样东西, 省一半 cache 带宽。
 *
 * 渲染顺序: 前 -> 后 + 每列一个 y 缓冲(遮挡), 同官方 "More performance" 一节。
 *
 * 编译: gcc -O3 -shared -fPIC -o libmcrender.so mcrender.c -lm
 */
#include <math.h>
#include <string.h>
#include <stdlib.h>

#define MAP_BITS   9
#define MAP_SIZE   (1 << MAP_BITS)
#define MAP_MASK   (MAP_SIZE - 1)
#define FOG_LEVELS 24
#define MAXW       1280
#define MAXH       800
#define MAXD_MAX   900
#define DET_N      128

/* ---- 地图: 每个格子一个 16bit 字, 高字节=高度, 低字节=颜色索引 ---- */
static unsigned char  *HM = 0;              /* Python 传来的高度图 */
static unsigned short *HC = 0;              /* 打包后的高度+颜色   */

/* ★ 调色板 = 【地形类型】×【明暗级】, 不是"高度->颜色"渐变
 *
 *   以前用 index==height 的连续色带, 于是每一级台阶的颜色都不一样 ->
 *   整个山坡变成一圈圈等高线(远看就是灯芯绒横纹)。
 *   "我的世界"里所有草方块是同一个绿, 区别只在【顶面亮 / 侧面暗】。
 *   所以: 先用高度定地形类型(水/沙/草/林/岩/雪), 再用坡向+细节定明暗级。
 */
#define NB  12                      /* 地形/方块类型数 */
#define NS  16                      /* 每类的明暗级数 (12*16=192 <= 256) */
static const unsigned char BAND_COL[NB][3] = {
    {  16,  36,  84 },   /* 0 深水   */
    {  40,  92, 152 },   /* 1 浅水   */
    { 226, 208, 158 },   /* 2 沙滩   */
    {  96, 160,  76 },   /* 3 草地   */
    {  62, 116,  58 },   /* 4 森林   */
    { 134, 130, 122 },   /* 5 岩石   */
    { 238, 242, 248 },   /* 6 雪山   */
    { 124,  86,  50 },   /* 7 原木   */
    {  52, 112,  46 },   /* 8 树叶   */
    { 158, 154, 146 },   /* 9 石砖   */
    { 232, 216, 168 },   /* 10 沙子  */
    { 250, 250, 255 },   /* 11 雪块  */
};
static unsigned char BAND_OF[256];
static unsigned char BASE[256][3];
static unsigned char PAL[FOG_LEVELS][256][3];

/* ★ 材质覆盖表 (和高度图同尺寸, 可缺省)
   0 = 按高度自动定材质; N = 强制用 (N-1) 号材质。
   有了它才能做【树】和【放置任意方块】—— 高度场本身只能表达"多高",
   表达不了"这是什么方块"。 */
static unsigned char *MAT = 0;

static unsigned char  DET[DET_N * DET_N];   /* 细节纹理 (可平铺) */
static unsigned char  SKYC[MAXH][3];
static float          DIRX[MAXW], DIRY[MAXW];
static float          KZ[MAXD_MAX + 1];

static int   RW = 512, RH = 300;
static int   OUTW = 1024, OUTH = 600;
static float FOCAL = 256.0f;
/* ★ 地形竖直缩放: 官方用 scale_height(120/600屏) 把【高度】和【焦距】解耦。
   焦距由视场角决定(几何), 而地形起伏多大是审美问题 —— 混在一起用会让
   地形显得又陡又尖, 近处每一格都糊成一根竖条。 */
static float HSCALE = 0.42f;
/* ★ 台阶描边: 每条竖带最下面一行压暗 —— 地形每一级台阶之间就多一道
   暗缝, 方块感立刻出来 (纯色平台是看不出"方块"的)。 */
static int   EDGE = 1;
static float EDGE_K = 0.78f;
static int   EDGE_MINH = 12;      /* 只有厚度 >= 这么多像素的台阶才描边,
                                    否则远处每一级台阶都变成一条细横纹 */

/* ★ 准星指着的方块: 渲染时把它染成高亮色, 挖/放才有明确的视觉反馈。
   以前没有任何反馈, 玩家根本不知道自己瞄的是哪一块。 */
static int   HILITE_X = -1, HILITE_Y = -1;
static int   WATER_ANIM = 1;     /* 水面轻微流动 */
static int   PHASE = 0;          /* 帧相位, 驱动水波 */
static int   INITED = 0;
static float KZ_FOCAL = -1.0f;
static int   TMP_RES = -1;
static unsigned char *TMP = 0;

/* 光照方向(西北偏上)与强度
   ★ 体素渲染的地形很平滑(实测相邻格平均 |dh| 只有 1), 单靠坡向算出来的
     明暗几乎看不见, 山丘会变成一片平的绿剪影。所以用【细+粗】两个尺度
     的差分叠加, 再配一个较强的细节噪声 —— 有分带限幅兜着, 不怕跨带。 */
#define SHADE_K1    5.5f    /* ±1 格差分(细节) */
#define SHADE_K3    2.2f    /* ±3 格差分(大形) */
#define DETAIL_K    0.16f

/* 每一段的索引范围 (供着色限幅用, 免得草地被"染"成水面) */
static unsigned char BLO[256], BHI[256];

/* 天际线锚定的天空色: 地平线处=雾色(浅), 往上到深蓝 */
#define SKY_H_R 198
#define SKY_H_G 222
#define SKY_H_B 244
#define SKY_T_R  46
#define SKY_T_G  88
#define SKY_T_B 178

/* 渲染跳过区: 这些输出像素每帧都会被 Python 的 HUD/按钮盖掉, 别白画 */
static int   SKIP_TOP = 0;
static int   HOLE_X0 = 0, HOLE_Y0 = 0, HOLE_X1 = 0, HOLE_Y1 = 0;

/* 地图取整: (int) 是向零截断, 对负坐标会取错格子(-0.5 -> 0 而不是 -1),
   在地图接缝处会出现一条"假墙"。加一个 512 的整数倍再 & 就正确了。 */
#define CELL(v)  ((((int)((v) + 8192.0f)) & MAP_MASK))

/*=====================================================================
 *  初始化
 *===================================================================*/

/* 索引 -> 颜色 的连续色带
   ★ 分段的边界是照【实测高度分布】定的, 不是均分:
      分位数 10%=58 25%=101 50%=143 75%=184 90%=207 95%=222
      所以水 ~10%, 沙滩 ~5%, 草地最宽(~55%), 森林 ~20%, 岩石 ~8%, 雪山 ~4%
      均分的话草地会太窄、沙滩太宽, 整张图看着像沙漠 + 游泳池。 */
static void build_base(void)
{
    /* 高度 -> 地形类型. 边界照【实测高度分位数】定, 不是均分:
       分位数 10%=58 25%=101 50%=143 75%=184 90%=207 95%=222
       所以水 ~10%, 沙滩 ~5%, 草地最宽, 森林 ~20%, 岩石 ~8%, 雪山 ~4%。 */
    static const int TH[6] = { 39, 58, 76, 175, 207, 229 };
    int i, b, s;
    for (i = 0; i < 256; i++) {
        b = 0;
        while (b < 6 && i >= TH[b]) b++;
        BAND_OF[i] = (unsigned char)b;
    }
    for (b = 0; b < NB; b++) {
        for (s = 0; s < NS; s++) {
            /* 明暗级 -> 亮度系数 0.45 .. 1.05 */
            float k = 0.45f + 0.60f * (s / (float)(NS - 1));
            int idx = b * NS + s;
            int r = (int)(BAND_COL[b][0] * k);
            int g = (int)(BAND_COL[b][1] * k);
            int bl = (int)(BAND_COL[b][2] * k);
            BASE[idx][0] = (unsigned char)(r > 255 ? 255 : r);
            BASE[idx][1] = (unsigned char)(g > 255 ? 255 : g);
            BASE[idx][2] = (unsigned char)(bl > 255 ? 255 : bl);
        }
    }
}

/* 雾: 把调色板按距离向地平线雾色过渡, 预乘成 PAL[雾级][索引] */
static void build_pal(void)
{
    int f, i;
    for (f = 0; f < FOG_LEVELS; f++) {
        float t = f / (float)(FOG_LEVELS - 1);
        t = t * t;                        /* 远处雾更浓 */
        for (i = 0; i < 256; i++) {
            PAL[f][i][0] = (unsigned char)(BASE[i][0] + (SKY_H_R - BASE[i][0]) * t);
            PAL[f][i][1] = (unsigned char)(BASE[i][1] + (SKY_H_G - BASE[i][1]) * t);
            PAL[f][i][2] = (unsigned char)(BASE[i][2] + (SKY_H_B - BASE[i][2]) * t);
        }
    }
}

/* 高亮色 (准星指着的方块) */
static const unsigned char HICOL[3] = { 255, 236, 120 };

/* 细节纹理: 多尺度平滑值噪声(4/8/16/32/64 格子, 幅度逐级减半)再平铺。
   直接模糊随机数只能得到很"碎"的椒盐, 投影到沙滩交界处会变成锯齿;
   多尺度噪声有大块的明暗团, 更像官方 colormap 里的草皮/岩理。 */
static void build_det(void)
{
    float acc[DET_N * DET_N];
    unsigned char g[64 * 64];
    unsigned int s = 20260924u;
    float amp = 1.0f, tot = 0.0f;
    int oct, x, y, i;
    for (i = 0; i < DET_N * DET_N; i++) acc[i] = 0.0f;
    for (oct = 0; oct < 5; oct++) {
        int n = 4 << oct;                       /* 4, 8, 16, 32, 64 */
        for (i = 0; i < n * n; i++) {
            s = s * 1103515245u + 12345u;
            g[i] = (unsigned char)((s >> 16) & 0xFF);
        }
        tot += amp;
        for (y = 0; y < DET_N; y++) {
            float fy = y * n / (float)DET_N;
            int y0 = (int)fy, y1 = (y0 + 1) % n;
            float ty = fy - y0;
            for (x = 0; x < DET_N; x++) {
                float fx = x * n / (float)DET_N;
                int x0 = (int)fx, x1 = (x0 + 1) % n;
                float tx = fx - x0;
                float v = g[y0 * n + x0] * (1 - tx) * (1 - ty)
                        + g[y0 * n + x1] * tx * (1 - ty)
                        + g[y1 * n + x0] * (1 - tx) * ty
                        + g[y1 * n + x1] * tx * ty;
                acc[y * DET_N + x] += v * amp;
            }
        }
        amp *= 0.5f;
    }
    for (i = 0; i < DET_N * DET_N; i++) {
        float v = acc[i] / tot;
        if (v < 0.0f) v = 0.0f;
        if (v > 255.0f) v = 255.0f;
        DET[i] = (unsigned char)v;
    }
}

/* ★ 烘焙一个格子的颜色索引 = 高度 + 坡向明暗 + 细节噪声
   这正是官方说的 "colormap 里已经包含明暗和阴影"。
   最后按【所属色带】限幅: 不让草地的明暗偏移把颜色染成水面/雪, 否则
   平坦草场上会冒出一片蓝色"游泳池"。 */
static unsigned char bake_one(int x, int y)
{
    int xm1 = (x - 1) & MAP_MASK, xp1 = (x + 1) & MAP_MASK;
    int xm3 = (x - 3) & MAP_MASK, xp3 = (x + 3) & MAP_MASK;
    int ym1 = ((y - 1) & MAP_MASK) * MAP_SIZE, yp1 = ((y + 1) & MAP_MASK) * MAP_SIZE;
    int ym3 = ((y - 3) & MAP_MASK) * MAP_SIZE, yp3 = ((y + 3) & MAP_MASK) * MAP_SIZE;
    int yc = y * MAP_SIZE;
    int h  = HM[yc + x];
    int g1 = (HM[yc + xp1] - HM[yc + xm1]) + (HM[yp1 + x] - HM[ym1 + x]);
    int g3 = (HM[yc + xp3] - HM[yc + xm3]) + (HM[yp3 + x] - HM[ym3 + x]);
    /* 光源在西北: 法线 n=(-dh/dx,-dh/dy,1), L=(-1,-1,1) => 亮度 ~ 1-(gx+gy) */
    int sh = (int)(-(g1 * SHADE_K1 + g3 * SHADE_K3));
    int d  = (int)(((int)DET[(y & (DET_N - 1)) * DET_N + (x & (DET_N - 1))] - 128)
                   * DETAIL_K);
    /* 明暗级: 平坦台阶顶面 = 中间偏亮, 台阶侧面(有台阶落差)直接压到最暗 */
    int s = NS / 2 + sh / 8 + d / 4;
    int band;
    if (s < 0) s = 0;
    if (s > NS - 1) s = NS - 1;
    /* ★ 材质: 有覆盖表就听它的(树/放置的方块), 否则按高度自动定 */
    band = MAT ? (MAT[yc + x] ? (MAT[yc + x] - 1) : BAND_OF[h]) : BAND_OF[h];
    if (band >= NB) band = NB - 1;
    return (unsigned char)(band * NS + s);
}

/* 整张图重烘焙 */
static void bake_color(void)
{
    int x, y;
    if (HC) { free(HC); HC = 0; }
    HC = (unsigned short *)malloc((size_t)MAP_SIZE * MAP_SIZE * sizeof(unsigned short));
    if (!HC) return;
    for (y = 0; y < MAP_SIZE; y++) {
        int yc = y * MAP_SIZE;
        for (x = 0; x < MAP_SIZE; x++)
            HC[yc + x] = (unsigned short)((HM[yc + x] << 8) | bake_one(x, y));
    }
}

/* 只重烘焙一块区域的颜色 (挖/放之后用, 比整张重算快几百倍) */
void mc_rebake(int cx, int cy, int r)
{
    int x, y, dx, dy;
    int rr = r + 3;                       /* 明暗要读 ±3 的邻居 */
    if (!HC || !HM) return;
    for (dy = -rr; dy <= rr; dy++) {
        y = (cy + dy) & MAP_MASK;
        for (dx = -rr; dx <= rr; dx++) {
            x = (cx + dx) & MAP_MASK;
            HC[y * MAP_SIZE + x] =
                (unsigned short)((HM[y * MAP_SIZE + x] << 8) | bake_one(x, y));
        }
    }
}

static void ensure_tmp(void)
{
    int key = RW * 10000 + RH;
    if (TMP && TMP_RES == key) return;
    if (TMP) free(TMP);
    TMP = (unsigned char *)malloc((size_t)RW * RH * 3);
    TMP_RES = key;
}

static void ensure_kz(void)
{
    int i;
    if (KZ_FOCAL == FOCAL) return;
    KZ[0] = 0.0f;
    for (i = 1; i <= MAXD_MAX; i++) KZ[i] = FOCAL / (float)i;
    KZ_FOCAL = FOCAL;
}

void mc_init(unsigned char *hm, int bits)
{
    HM = hm;
    (void)bits;
    build_base();
    build_pal();
    build_det();
    bake_color();
    INITED = 1;
}

void mc_setres(int rw, int rh, int ow, int oh, float focal)
{
    int i;
    float half;
    RW = rw; RH = rh; OUTW = ow; OUTH = oh;
    if (RW < 32) RW = 32;
    if (RH < 24) RH = 24;
    if (RW > MAXW) RW = MAXW;
    if (RH > MAXH) RH = MAXH;
    /* focal <= 0 时按官方几何自动取: 水平半视角 45° => 焦距 = 列数/2 */
    FOCAL = (focal > 0.0f) ? focal : (RW * 0.5f);
    ensure_tmp();
    /* ★ 平面投影: 第 i 列的横向偏移 cx ∈ [-1,1] (半视角 45°) */
    half = (RW - 1) * 0.5f;
    for (i = 0; i < RW; i++)
        DIRX[i] = (i - half) / half;      /* 先存 cx, 渲染前再乘到方向向量上 */
    build_pal();
    ensure_kz();
}

void mc_set_focal(float focal)
{
    FOCAL = focal;
    ensure_kz();
}

/* 地形竖直缩放 (官方 scale_height 的对应物)。1.0 = 不缩放 */
void mc_set_hscale(float hs)
{
    if (hs < 0.05f) hs = 0.05f;
    if (hs > 4.0f) hs = 4.0f;
    HSCALE = hs;
}

/* 台阶描边开关与强度 */
void mc_set_edge(int on, float k, int minh)
{
    EDGE = on ? 1 : 0;
    if (k > 0.05f && k <= 1.0f) EDGE_K = k;
    if (minh >= 1 && minh <= 64) EDGE_MINH = minh;
}

/* 准星指向的方块 (挖/放的目标), 传 -1 取消高亮 */
void mc_set_highlight(int hx, int hy)
{
    HILITE_X = hx; HILITE_Y = hy;
}

/* 水面流动开关 + 帧相位 */
void mc_set_water(int on) { WATER_ANIM = on ? 1 : 0; }
void mc_set_phase(int ph) { PHASE = ph & 1023; }

/* 材质覆盖表 (可传 NULL 取消)
   ★ 必须重新烘焙: HC 里的颜色索引是在 mc_init 时算好的, 只改指针不重算
     的话材质永远不生效(Python 那边是先 mc_init 再 mc_set_mat)。 */
void mc_set_mat(unsigned char *mat)
{
    MAT = mat;
    bake_color();
}

/* 材质数/明暗级数, 给 Python 拼调色板用 */
int mc_band_count(void) { return NB; }
int mc_shade_count(void) { return NS; }

/* 设置"不画"的区域(输出像素坐标): 顶部 skip 行 + 一个矩形洞 */
void mc_set_skip(int skip_top, int hx0, int hy0, int hx1, int hy1)
{
    SKIP_TOP = skip_top < 0 ? 0 : skip_top;
    HOLE_X0 = hx0; HOLE_Y0 = hy0; HOLE_X1 = hx1; HOLE_Y1 = hy1;
}

/*=====================================================================
 *  天空
 *===================================================================*/
/* 以地平线为锚: 地平线处 = 雾色(会一直用到底部), 往上渐变成深蓝。
   这样远处地形淡出到雾色时, 和天空在交界处颜色完全一致, 不会出现
   "地形和天空之间一条硬边"。 */
static void build_sky(float horizon)
{
    int y;
    for (y = 0; y < RH && y < MAXH; y++) {
        float t = (horizon - (float)y) / 150.0f;
        if (t < 0.0f) t = 0.0f;
        if (t > 1.0f) t = 1.0f;
        t = powf(t, 0.72f);
        SKYC[y][0] = (unsigned char)(SKY_H_R + (SKY_T_R - SKY_H_R) * t);
        SKYC[y][1] = (unsigned char)(SKY_H_G + (SKY_T_G - SKY_H_G) * t);
        SKYC[y][2] = (unsigned char)(SKY_H_B + (SKY_T_B - SKY_H_B) * t);
    }
}

/*=====================================================================
 *  放大到输出 (RW*RH -> OUTW*OUTH 整数倍最近邻)
 *  bgr=1 时输出 BGR(framebuffer), 否则 RGB
 *===================================================================*/
static void upscale_to(unsigned char *out, int stride, int bgr)
{
    int x, y, sx, sy2;
    sx = OUTW / RW; if (sx < 1) sx = 1;
    sy2 = OUTH / RH; if (sy2 < 1) sy2 = 1;

    /* ★ 原生分辨率 (1:1) 走 memcpy 快路径 —— 逐像素循环在 1024x600 下
       要多花好几毫秒, 而这里只是把 TMP 原样搬过去 */
    if (sx == 1 && sy2 == 1) {
        int rowlen = RW * 3;
        for (y = 0; y < RH && y < OUTH; y++) {
            unsigned char *d;
            if (y < SKIP_TOP) continue;
            d = out + (size_t)y * stride;
            if (y >= HOLE_Y0 && y < HOLE_Y1 && HOLE_X1 > HOLE_X0) {
                int a = HOLE_X0 * 3, b2 = HOLE_X1 * 3;
                if (a > rowlen) a = rowlen;
                if (b2 > rowlen) b2 = rowlen;
                if (a > 0) memcpy(d, TMP + (size_t)y * rowlen, (size_t)a);
                if (b2 < rowlen)
                    memcpy(d + b2, TMP + (size_t)y * rowlen + b2,
                           (size_t)(rowlen - b2));
            } else {
                memcpy(d, TMP + (size_t)y * rowlen, (size_t)rowlen);
            }
        }
        return;
    }

    for (y = 0; y < RH; y++) {
        int oy = y * sy2;
        int hole_row;
        unsigned char *rowp = TMP + (size_t)y * RW * 3;
        if (oy + sy2 <= SKIP_TOP) continue;              /* 整行都在 HUD 里 */
        hole_row = (oy >= HOLE_Y0 && oy + sy2 <= HOLE_Y1);
        for (x = 0; x < RW; x++) {
            const unsigned char *s = rowp + (size_t)x * 3;
            unsigned char r = s[0], g = s[1], b = s[2];
            int j, k, ox = x * sx;
            unsigned char *d0;
            if (hole_row && ox >= HOLE_X0 && ox + sx <= HOLE_X1)
                continue;                                 /* 整块都在按钮里 */
            d0 = out + (size_t)oy * stride + (size_t)ox * 3;
            if (bgr) {
                for (j = 0; j < sy2; j++) {
                    unsigned char *d = d0 + (size_t)j * stride;
                    for (k = 0; k < sx; k++) { d[0] = b; d[1] = g; d[2] = r; d += 3; }
                }
            } else {
                for (j = 0; j < sy2; j++) {
                    unsigned char *d = d0 + (size_t)j * stride;
                    for (k = 0; k < sx; k++) { d[0] = r; d[1] = g; d[2] = b; d += 3; }
                }
            }
        }
    }
}

/*=====================================================================
 *  ★ 直接渲染到目标 (原生分辨率)
 *
 *  以前不管什么分辨率都先画进 TMP, 再放大到输出。原生 1:1 时那个"放大"
 *  只是整屏 memcpy, 纯浪费 —— 而且我图省事写的 memcpy 快路径忘了处理
 *  BGR(显存是 BGR, TMP 是 RGB), 结果把红蓝对调: 淡蓝天空变成橙色,
 *  沙地变成浅蓝。正确做法是【根本不经过中间缓冲】, 每个像素按目标的
 *  通道顺序直接写进去, 顺便省掉整个放大步骤。
 *===================================================================*/
static unsigned char *DST = 0;
static int   DST_STRIDE = 0;
static int   DST_BGR = 0;
static int   DST_DIRECT = 0;

static inline unsigned char *pxat(int x, int y)
{
    if (DST_DIRECT) return DST + (size_t)y * DST_STRIDE + (size_t)x * 3;
    return TMP + ((size_t)y * RW + x) * 3;
}

static inline void put3(unsigned char *p, unsigned char r, unsigned char g,
                        unsigned char b)
{
    if (DST_BGR) { p[0] = b; p[1] = g; p[2] = r; }
    else         { p[0] = r; p[1] = g; p[2] = b; }
}

/* 一条竖线, 自动避开 HUD 顶部和按钮矩形 (直接模式下才需要) */
static void fill_col(int x, int y0, int y1, int r, int g, int b)
{
    unsigned char *p;
    int a, e, y;
    if (y1 <= y0) return;
    if (!DST_DIRECT) {
        p = pxat(x, y0);
        for (y = y0; y < y1; y++) {
            put3(p, (unsigned char)r, (unsigned char)g, (unsigned char)b);
            p += RW * 3;
        }
        return;
    }
    if (y0 < SKIP_TOP) y0 = SKIP_TOP;
    if (y1 > OUTH) y1 = OUTH;
    if (y1 <= y0) return;
    if (x >= HOLE_X0 && x < HOLE_X1 && HOLE_Y1 > HOLE_Y0) {
        /* 这一列穿过按钮洞 -> 拆成洞上面和洞下面两段 */
        a = y0; e = y1 < HOLE_Y0 ? y1 : HOLE_Y0;
        p = pxat(x, a);
        for (y = a; y < e; y++) {
            put3(p, (unsigned char)r, (unsigned char)g, (unsigned char)b);
            p += DST_STRIDE;
        }
        a = y0 > HOLE_Y1 ? y0 : HOLE_Y1;
        p = pxat(x, a);
        for (y = a; y < y1; y++) {
            put3(p, (unsigned char)r, (unsigned char)g, (unsigned char)b);
            p += DST_STRIDE;
        }
        return;
    }
    p = pxat(x, y0);
    for (y = y0; y < y1; y++) {
        put3(p, (unsigned char)r, (unsigned char)g, (unsigned char)b);
        p += DST_STRIDE;
    }
}

/*=====================================================================
 *  主渲染 (官方算法 + 前->后 + y 缓冲)
 *===================================================================*/
static void render_core(float px, float py, float pz,
                        float yaw, float pitch, int maxd)
{
    int i, x, y, z;
    float horizon;
    float fx, fy, rx_, ry_;
    static float inv_maxd = 0.0f;
    static int   last_maxd = -1;

    if (!INITED || !HM || !HC || !DST) return;
    if (maxd > MAXD_MAX) maxd = MAXD_MAX;
    if (maxd < 8) maxd = 8;
    if (maxd != last_maxd) { inv_maxd = 1.0f / (float)maxd; last_maxd = maxd; }
    ensure_kz();

    /* 视点的前方和右方单位向量 (yaw: 0 = 朝 +Y) */
    fx = sinf(yaw);  fy = cosf(yaw);
    rx_ = cosf(yaw); ry_ = -sinf(yaw);

    /* 地平线: 屏幕行; pitch 为负 = 低头(地平线往上走, 露出更多地面) */
    horizon = RH * 0.5f + pitch * 160.0f;
    build_sky(horizon);

    /* ---- 1) 铺天空 ---- */
    if (DST_DIRECT) {
        for (y = SKIP_TOP; y < RH && y < OUTH; y++) {
            unsigned char r = SKYC[y][0], g = SKYC[y][1], b = SKYC[y][2];
            unsigned char *p = pxat(0, y);
            for (x = 0; x < RW; x++, p += 3) put3(p, r, g, b);
        }
    } else {
        for (y = 0; y < RH; y++) {
            unsigned char *row = TMP + (size_t)y * RW * 3;
            unsigned char r = SKYC[y][0], g = SKYC[y][1], b = SKYC[y][2];
            for (x = 0; x < RW; x++) { *row++ = r; *row++ = g; *row++ = b; }
        }
    }

    /* ---- 2) 逐列从近到远推进, 用地形覆盖天空 ---- */
    for (i = 0; i < RW; i++) {
        float cx = DIRX[i];                      /* ∈ [-1,1], 半视角 45° */
        float dx = fx + rx_ * cx;                /* 世界方向 (未归一) */
        float dy = fy + ry_ * cx;
        float wx = px, wy = py;
        float ybuf = (float)RH;
        int zz = 1, dz = 1;
        /* ★ LOD: 远处的步子迈大。
           z>70 之后每一段在屏幕上本来就只有 1~2 像素, 而且基本被雾盖住了,
           逐格采样纯属浪费。实测把 200 步降到 ~124 步, 渲染快三分之一,
           画面几乎看不出差别。 */
        while (zz < maxd) {
            unsigned short hc;
            int h, ci, y0, y1, cxi, cyi;
            const unsigned char *c;
            unsigned char r, g, b;
            wx += dx * (float)dz;
            wy += dy * (float)dz;
            cxi = CELL(wx);
            cyi = CELL(wy);
            hc = HC[(cyi << MAP_BITS) + cxi];
            h  = hc >> 8;
            ci = hc & 0xFF;
            /* ★ 准星指着的那一格 -> 记下来, 颜色向白偏 60% */
            if (cxi == HILITE_X && cyi == HILITE_Y) ci = -1;
            /* 透视投影: 高度差 / 距离 * 焦距 * 竖直缩放 + 地平线 */
            y0 = (int)(horizon + (pz - (float)h) * (HSCALE * KZ[zz]));
            /* 边界比较用浮点: 整数截断会在边界恰好跨整数时让相邻两段
               都判成"不用画", 漏出 1 像素的天色裂缝 */
            if ((float)y0 >= ybuf) goto next_ray;
            if (ci < 0) {
                c = HICOL;                     /* 高亮块用固定亮色 */
            } else {
                /* ★ 水面波纹: 水是 band 0/1。让明暗级随格子坐标 + 帧相位
                   做一条横向的亮暗带, 看起来就是缓缓流动的波纹。
                   (只改明暗级, 不跨 band, 所以不会把水染成沙/草) */
                if (WATER_ANIM && (ci >> 4) <= 1) {
                    int ph = (cyi * 2 + PHASE) & 7;
                    int sh = (ci & (NS - 1)) + ((ph < 4) ? 1 : -1);
                    if (sh < 0) sh = 0;
                    if (sh > NS - 1) sh = NS - 1;
                    ci = (ci & ~(NS - 1)) | sh;
                }
                {
                    float ft = zz * inv_maxd;
                    int fi = (int)(ft * ft * (FOG_LEVELS - 1));
                    if (fi > FOG_LEVELS - 1) fi = FOG_LEVELS - 1;
                    c = PAL[fi][ci];
                }
            }
            y1 = (int)ybuf;
            ybuf = (float)y0;
            if (y0 < 0) y0 = 0;
            if (y1 > RH) y1 = RH;
            if (y1 > y0) {
                r = c[0]; g = c[1]; b = c[2];
                if (DST_DIRECT && !(i >= HOLE_X0 && i < HOLE_X1 &&
                                    HOLE_Y1 > HOLE_Y0)) {
                    /* 快路径: 这一列不在按钮洞里, 直接一次写完, 不走函数调用 */
                    int ay = y0 < SKIP_TOP ? SKIP_TOP : y0;
                    int by2 = y1 > OUTH ? OUTH : y1;
                    if (by2 > ay) {
                        unsigned char *p2 = pxat(i, ay);
                        int yy;
                        for (yy = ay; yy < by2; yy++) {
                            put3(p2, r, g, b);
                            p2 += DST_STRIDE;
                        }
                    }
                } else {
                    fill_col(i, y0, y1, r, g, b);
                }
                /* 台阶描边: 把这一带最下面一行压暗
                   ★ 以前这里又调了一次 fill_col(一行) —— 一帧 5 万多次带
                     6 个分支的函数调用, 直接内联成一个像素写快得多 */
                if (EDGE && y1 - y0 >= EDGE_MINH) {
                    int ey = y1 - 1;
                    int sk = DST_DIRECT && (ey < SKIP_TOP ||
                             (i >= HOLE_X0 && i < HOLE_X1 &&
                              ey >= HOLE_Y0 && ey < HOLE_Y1));
                    if (ey >= 0 && ey < OUTH && !sk) {
                        put3(pxat(i, ey),
                             (unsigned char)(r * EDGE_K),
                             (unsigned char)(g * EDGE_K),
                             (unsigned char)(b * EDGE_K));
                    }
                }
            }
            if (ybuf <= 0.0f) break;
        next_ray:
            zz += dz;
            if (zz >= 110) dz = 3;
            else if (zz >= 48) dz = 2;
        }
    }
}

void mc_render(unsigned char *out, float px, float py, float pz,
               float yaw, float pitch, int maxd)
{
    DST = out; DST_STRIDE = OUTW * 3; DST_BGR = 0;
    DST_DIRECT = (RW == OUTW && RH == OUTH) ? 1 : 0;
    render_core(px, py, pz, yaw, pitch, maxd);
    if (!DST_DIRECT) upscale_to(out, OUTW * 3, 0);
}

/* 准星: 直接画在 framebuffer 上 */
static void draw_cross(unsigned char *fb, int stride)
{
    int cx = OUTW / 2, cy = OUTH / 2, k, t;
    int arm = 13, gap = 4;
    for (k = 0; k < 2; k++) {
        int y0 = cy - 1 + k, x0;
        for (x0 = cx - arm; x0 < cx - gap; x0++) {
            unsigned char *p = fb + (size_t)y0 * stride + (size_t)x0 * 3;
            p[0] = 255; p[1] = 255; p[2] = 255;
        }
        for (x0 = cx + gap; x0 < cx + arm; x0++) {
            unsigned char *p = fb + (size_t)y0 * stride + (size_t)x0 * 3;
            p[0] = 255; p[1] = 255; p[2] = 255;
        }
        for (t = cy - arm; t < cy - gap; t++) {
            unsigned char *p = fb + (size_t)t * stride + (size_t)(cx - 1 + k) * 3;
            p[0] = 255; p[1] = 255; p[2] = 255;
        }
        for (t = cy + gap; t < cy + arm; t++) {
            unsigned char *p = fb + (size_t)t * stride + (size_t)(cx - 1 + k) * 3;
            p[0] = 255; p[1] = 255; p[2] = 255;
        }
    }
}

void mc_render_bgr(unsigned char *fb, int stride, float px, float py, float pz,
                   float yaw, float pitch, int maxd)
{
    DST = fb; DST_STRIDE = stride; DST_BGR = 1;
    DST_DIRECT = (RW == OUTW && RH == OUTH) ? 1 : 0;
    render_core(px, py, pz, yaw, pitch, maxd);
    if (!DST_DIRECT) upscale_to(fb, stride, 1);
    draw_cross(fb, stride);
}

/*=====================================================================
 *  拾取: 从视点沿【视线】找第一个挡住的格子 (和准星严格一致)
 *
 *  ★ 以前只沿 yaw 直线走, 完全忽略俯仰 —— 准星指着脚边, 它却去捡很远的
 *    一格, 于是"放一块"变成了在远处凭空竖一根细柱子(看着就是一条线)。
 *    现在按投影关系反推: 屏幕正中那条视线在水平距离 z 处的高度是
 *        rz = pz + pitch*160*z / (HSCALE*FOCAL)
 *    走到 rz 落到地形里, 就是准星指着的那个方块。
 *===================================================================*/
int mc_pick(float px, float py, float pz, float yaw, float pitch, int maxd,
            int *ox, int *oy, int *oz)
{
    float dx = sinf(yaw), dy = cosf(yaw);
    float dzd;
    float rx = px, ry = py, rz = pz;
    int z;
    if (!HC) return -1;
    if (maxd > MAXD_MAX) maxd = MAXD_MAX;
    if (HSCALE < 0.01f || FOCAL < 1.0f) return -1;
    dzd = pitch * 160.0f / (HSCALE * FOCAL);
    for (z = 1; z < maxd; z++) {
        int h, ix, iy;
        rx += dx; ry += dy; rz += dzd;
        ix = CELL(rx); iy = CELL(ry);
        h = HC[(iy << MAP_BITS) + ix] >> 8;
        if (rz <= (float)h) {
            *ox = ix; *oy = iy;
            if (oz) *oz = h;
            return 0;
        }
        if (rz < -4.0f) break;               /* 已经钻到地下了 */
    }
    return -1;
}

unsigned char *mc_hmap(void) { return HM; }

/* 调试: 取某个格子的 (高度, 颜色索引) */
int mc_cell(int x, int y, int *h, int *c)
{
    unsigned short w;
    if (!HC) return -1;
    w = HC[((y & MAP_MASK) << MAP_BITS) + (x & MAP_MASK)];
    if (h) *h = w >> 8;
    if (c) *c = w & 0xFF;
    return 0;
}

/* 调试: 取调色板颜色 (雾级 0) */
int mc_pal(int idx, int *r, int *g, int *b)
{
    if (idx < 0 || idx > 255) return -1;
    *r = PAL[0][idx][0]; *g = PAL[0][idx][1]; *b = PAL[0][idx][2];
    return 0;
}
