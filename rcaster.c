/*
 * rcaster.c —— Doom / Wolfenstein3D 式【光线投射】渲染器
 *
 * 和之前的体素空间渲染有什么本质区别:
 *   体素空间: 只有竖直柱子, 没有顶面/侧面, 屏幕每列是独立射线
 *             -> 地形永远像"糊在一起的色块", 做不出方块和墙
 *   光线投射: 世界是 2D 网格墙, 每列打一条 DDA 射线撞墙,
 *             把【贴好纹理的竖条】画出来。墙面轴对齐 -> 透视是硬的,
 *             纹理贴上去非常"实", 这就是 90 年代 3D 游戏的样子。
 *
 * 算法参考经典 Lodev raycasting 教程 (DDA + 垂直条带 + 纹理映射):
 *   1) 逐列算射线方向
 *   2) DDA 走格子直到撞到非空格
 *   3) 用【垂直距离】(不是欧氏距离) 算墙高, 避免鱼眼
 *   4) 从撞击点的小数部分取纹理 U 坐标, 竖着采样纹理画一整条
 *   5) 北/南面压暗一点 -> 转角能看出来(Wolf3D 的经典技巧)
 *   6) 地板/天花板用【逐行】反向投影贴图(每行距离是常数, 只算一次)
 *
 * 编译: gcc -O3 -shared -fPIC -o librcaster.so rcaster.c -lm
 */
#include <math.h>
#include <string.h>
#include <stdlib.h>

#define TEX       64
#define NTEX      8
#define MAXW      1280
#define MAXH      800
#define MAP_MAX   256

/* 纹理编号 */
#define T_BRICK   1
#define T_STONE   2
#define T_WOOD    3
#define T_METAL   4
#define T_DOOR    5
#define T_GRASS   6      /* 地板 */
#define T_CEIL    7      /* 天花板 */

static unsigned char TEXDATA[NTEX][TEX * TEX * 3];

static const unsigned char *MAP = 0;
static int   MAPW = 64, MAPH = 64;

static int   RW = 512, RH = 300;
static int   OUTW = 1024, OUTH = 600;
static float FOCAL = 394.0f;
static float EYEH = 0.5f;              /* 眼高, 单位=格子高 (0.5 = 墙的一半) */
static float FOG = 0.012f;             /* 距离雾强度 */
static int   SHADE_SIDE = 1;           /* 南北面压暗 */
static int   DRAW_FLOOR = 1;

static unsigned char *TMP = 0;
static int   TMP_RES = -1;
static float *ZBUF = 0;                /* 每列垂直距离, 给精灵用 */
static float DIRX[MAXW], DIRY[MAXW];   /* 每列的射线方向 */

/* 不画的区域(HUD 会盖住) */
static int   SKIP_TOP = 0;
static int   HOLE_X0 = 0, HOLE_Y0 = 0, HOLE_X1 = 0, HOLE_Y1 = 0;

static int   INITED = 0;

/*=====================================================================
 *  程序化纹理: 不依赖任何外部图片, 板上 init 时几毫秒生成好
 *===================================================================*/
static unsigned int rnd_state;
static unsigned int rnd(void)
{
    rnd_state = rnd_state * 1103515245u + 12345u;
    return (rnd_state >> 16) & 0x7FFF;
}
static int clamp255(int v) { return v < 0 ? 0 : (v > 255 ? 255 : v); }

static void put(unsigned char *t, int x, int y, int r, int g, int b)
{
    unsigned char *p;
    if (x < 0 || y < 0 || x >= TEX || y >= TEX) return;
    p = t + (y * TEX + x) * 3;
    p[0] = (unsigned char)clamp255(r);
    p[1] = (unsigned char)clamp255(g);
    p[2] = (unsigned char)clamp255(b);
}

/* 砖墙: 错缝砖 + 灰浆 + 每块砖颜色略不同 */
static void tex_brick(unsigned char *t, int br, int bg, int bb, int seed)
{
    int x, y, row, col;
    rnd_state = (unsigned int)seed * 2654435761u + 1u;
    for (y = 0; y < TEX; y++) {
        row = y / 16;                       /* 16 像素一层砖 */
        for (x = 0; x < TEX; x++) {
            int off = (row & 1) ? 8 : 0;    /* 错缝 */
            int bx = ((x + off) % 16);
            int by = (y % 16);
            int mortar = (bx < 2 || by < 2);
            if (mortar) {
                put(t, x, y, 96, 92, 86);
            } else {
                unsigned int h = (unsigned int)(row * 37 + ((x + off) / 16) * 91 + seed * 7);
                int v = (int)(h % 41) - 20;             /* 每块砖的变化 */
                int n = (int)(rnd() % 17) - 8;          /* 表面颗粒 */
                put(t, x, y, br + v + n, bg + v + n, bb + v + n);
                /* 上沿高光 / 下沿阴影 -> 有立体感 */
                if (by == 2 || by == 3) put(t, x, y, br + v + 26, bg + v + 24, bb + v + 20);
                if (by == 14 || by == 15) put(t, x, y, br + v - 24, bg + v - 24, bb + v - 22);
            }
        }
    }
}

/* 石墙: 大块方石, 边角倒角 */
static void tex_stone(unsigned char *t, int seed)
{
    int x, y;
    rnd_state = (unsigned int)seed * 40503u + 7u;
    for (y = 0; y < TEX; y++) {
        for (x = 0; x < TEX; x++) {
            int bx = x % 32, by = y % 32;
            int v = 128 + (int)(rnd() % 31) - 15;
            if (bx == 0 || by == 0) v -= 42;              /* 缝 */
            if (bx == 1 || by == 1) v -= 16;
            if (bx == 30 || bx == 31 || by == 30 || by == 31) v += 14;
            put(t, x, y, v, v - 3, v - 10);
        }
    }
}

/* 木板墙: 竖条木纹 */
static void tex_wood(unsigned char *t, int seed)
{
    int x, y;
    rnd_state = (unsigned int)seed * 2246822519u + 3u;
    for (x = 0; x < TEX; x++) {
        int plank = x / 16;
        int edge = ((x % 16) == 0 || (x % 16) == 15);
        int base = 116 + (plank * 23) % 31;
        int grain = (int)(rnd() % 13) - 6;
        for (y = 0; y < TEX; y++) {
            int g2 = (int)(sinf((y + plank * 9) * 0.35f) * 9.0f);
            int v = edge ? base - 48 : base + grain + g2;
            put(t, x, y, v + 26, (int)(v * 0.68f) + 6, (int)(v * 0.36f));
        }
    }
}

/* 金属板: 面板 + 铆钉 */
static void tex_metal(unsigned char *t, int seed)
{
    int x, y;
    (void)seed;
    for (y = 0; y < TEX; y++) {
        for (x = 0; x < TEX; x++) {
            int bx = x % 32, by = y % 32;
            int v = 116 + ((bx < 2 || by < 2) ? -34 : 0);
            if (bx == 30 || by == 30) v -= 20;
            /* 铆钉 */
            {
                int dx = bx - 5, dy = by - 5;
                if (dx * dx + dy * dy < 6) v += 62;
                dx = bx - 26; dy = by - 26;
                if (dx * dx + dy * dy < 6) v += 62;
            }
            v += (int)(rnd() % 9) - 4;
            put(t, x, y, v, v + 4, v + 12);
        }
    }
}

/* 门: 深色金属门 + 中间缝 + 把手 */
static void tex_door(unsigned char *t)
{
    int x, y;
    for (y = 0; y < TEX; y++) {
        for (x = 0; x < TEX; x++) {
            int v = 96;
            if (x < 3 || x > 60 || y < 3 || y > 60) v = 58;
            if (x >= 30 && x <= 33) v = 48;               /* 中缝 */
            if (y >= 26 && y <= 32 && x >= 8 && x <= 55) v = 118;  /* 横档 */
            if (x >= 44 && x <= 50 && y >= 34 && y <= 40) v = 196; /* 把手 */
            put(t, x, y, v, (int)(v * 0.92f), (int)(v * 0.72f));
        }
    }
}

/* 地板: 方格地砖 */
static void tex_tile(unsigned char *t, int seed)
{
    int x, y;
    rnd_state = (unsigned int)seed * 668265263u + 11u;
    for (y = 0; y < TEX; y++) {
        for (x = 0; x < TEX; x++) {
            int bx = x % 32, by = y % 32;
            int dark = ((x / 32) + (y / 32)) & 1;
            int v = dark ? 74 : 104;
            if (bx < 2 || by < 2) v -= 26;
            v += (int)(rnd() % 13) - 6;
            put(t, x, y, v + 10, v + 6, v);
        }
    }
}

/* 草地地板 */
static void tex_grass(unsigned char *t, int seed)
{
    int x, y;
    rnd_state = (unsigned int)seed * 747796405u + 5u;
    for (y = 0; y < TEX; y++) {
        for (x = 0; x < TEX; x++) {
            int v = 84 + (int)(rnd() % 41) - 20;
            put(t, x, y, (int)(v * 0.55f), v + 34, (int)(v * 0.42f));
        }
    }
}

/* 天花板: 深色石板 */
static void tex_ceil(unsigned char *t)
{
    int x, y;
    for (y = 0; y < TEX; y++) {
        for (x = 0; x < TEX; x++) {
            int bx = x % 16, by = y % 16;
            int v = 56 + ((bx < 1 || by < 1) ? -22 : 0);
            v += (int)(rnd() % 9) - 4;
            put(t, x, y, v, v, v + 8);
        }
    }
}

static void build_textures(void)
{
    tex_brick(TEXDATA[T_BRICK], 146, 74, 58, 1);
    tex_stone(TEXDATA[T_STONE], 2);
    tex_wood(TEXDATA[T_WOOD], 3);
    tex_metal(TEXDATA[T_METAL], 4);
    tex_door(TEXDATA[T_DOOR]);
    tex_tile(TEXDATA[T_GRASS], 6);
    tex_ceil(TEXDATA[T_CEIL]);
    /* 第 0 号不用; 让 T_GRASS 变成方格地砖, 草地在 8 号之外先不管 */
}

/*=====================================================================
 *  接口
 *===================================================================*/
void rc_init(const unsigned char *map, int w, int h)
{
    MAP = map;
    MAPW = (w > 0 && w <= MAP_MAX) ? w : 64;
    MAPH = (h > 0 && h <= MAP_MAX) ? h : 64;
    build_textures();
    INITED = 1;
}

void rc_setres(int rw, int rh, int ow, int oh, float focal)
{
    int i;
    float half, t;
    RW = rw; RH = rh; OUTW = ow; OUTH = oh;
    if (RW < 32) RW = 32;
    if (RH < 24) RH = 24;
    if (RW > MAXW) RW = MAXW;
    if (RH > MAXH) RH = MAXH;
    /* 焦距: focal<=0 时按 66° 水平视场角自动取 (Doom/Wolf3D 常用值) */
    FOCAL = (focal > 0.0f) ? focal : (RW * 0.5f / tanf(0.5760f));
    if (TMP) free(TMP);
    TMP = (unsigned char *)malloc((size_t)RW * RH * 3);
    if (ZBUF) free(ZBUF);
    ZBUF = (float *)malloc((size_t)RW * sizeof(float));
    TMP_RES = RW * 10000 + RH;
    /* 每列的射线方向: 屏幕 x -> [-1,1] -> 视角内均匀分布(平面投影) */
    half = (RW - 1) * 0.5f;
    t = tanf(0.5760f);                    /* 半视角约 33° */
    for (i = 0; i < RW; i++)
        DIRX[i] = ((i - half) / half) * t;   /* 存的是 tan 偏移, 用时乘上右向量 */
    (void)TMP_RES;
}

void rc_set_eye(float eyeh)
{
    if (eyeh > 0.05f && eyeh < 2.0f) EYEH = eyeh;
}

void rc_set_fog(float f)
{
    if (f >= 0.0f && f < 1.0f) FOG = f;
}

void rc_set_floor(int on) { DRAW_FLOOR = on ? 1 : 0; }
void rc_set_side(int on)  { SHADE_SIDE = on ? 1 : 0; }

void rc_set_skip(int skip_top, int hx0, int hy0, int hx1, int hy1)
{
    SKIP_TOP = skip_top < 0 ? 0 : skip_top;
    HOLE_X0 = hx0; HOLE_Y0 = hy0; HOLE_X1 = hx1; HOLE_Y1 = hy1;
}

float *rc_zbuf(void) { return ZBUF; }

/*=====================================================================
 *  放大到输出 (RW*RH -> OUTW*OUTH 整数倍最近邻)
 *===================================================================*/
static void upscale_to(unsigned char *out, int stride, int bgr)
{
    int x, y, sx, sy2;
    sx = OUTW / RW; if (sx < 1) sx = 1;
    sy2 = OUTH / RH; if (sy2 < 1) sy2 = 1;
    for (y = 0; y < RH; y++) {
        int oy = y * sy2;
        int hole_row;
        unsigned char *rowp = TMP + (size_t)y * RW * 3;
        if (oy + sy2 <= SKIP_TOP) continue;
        hole_row = (oy >= HOLE_Y0 && oy + sy2 <= HOLE_Y1);
        for (x = 0; x < RW; x++) {
            const unsigned char *s = rowp + (size_t)x * 3;
            unsigned char r = s[0], g = s[1], b = s[2];
            int j, k, ox = x * sx;
            unsigned char *d0;
            if (hole_row && ox >= HOLE_X0 && ox + sx <= HOLE_X1) continue;
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

/* 雾/距离衰减: 把颜色按距离往"远处色"压 */
static int fog_k(float dist, int *sh)
{
    float f = 1.0f - dist * FOG;
    if (f < 0.12f) f = 0.12f;
    if (f > 1.0f) f = 1.0f;
    *sh = (int)(f * 256.0f);
    return *sh;
}

/*=====================================================================
 *  主渲染
 *===================================================================*/
static void render_core(float px, float py, float yaw, float pitch)
{
    int x, y;
    float dirX = sinf(yaw), dirY = cosf(yaw);
    float planeX = cosf(yaw), planeY = -sinf(yaw);
    float horizon = RH * 0.5f + pitch * 220.0f;
    if (!INITED || !MAP || !TMP) return;

    /* ---- 1) 天花板 / 地板: 逐行反向投影贴图 ----
       同一屏幕行上所有像素的"地板距离"是同一个常数, 所以每行只算一次
       除法, 然后沿行线性推进世界坐标 —— 这是 Lodev 那套写法。 */
    if (DRAW_FLOOR) {
        for (y = 0; y < RH; y++) {
            int is_floor = (y > (int)horizon);
            float p = is_floor ? (y - horizon) : (horizon - y);
            float rowDist, stepX, stepY, fx, fy;
            const unsigned char *tex = TEXDATA[is_floor ? T_GRASS : T_CEIL];
            unsigned char *row = TMP + (size_t)y * RW * 3;
            int sh, i;
            if (p < 0.5f) p = 0.5f;
            rowDist = (is_floor ? EYEH : (1.0f - EYEH)) * FOCAL / p;
            fog_k(rowDist, &sh);
            stepX = rowDist * (planeX * 2.0f * tanf(0.5760f)) / RW;
            stepY = rowDist * (planeY * 2.0f * tanf(0.5760f)) / RW;
            fx = px + rowDist * (dirX - planeX * tanf(0.5760f));
            fy = py + rowDist * (dirY - planeY * tanf(0.5760f));
            for (i = 0; i < RW; i++) {
                int tx = ((int)(fx * TEX)) & (TEX - 1);
                int ty = ((int)(fy * TEX)) & (TEX - 1);
                const unsigned char *s = tex + (ty * TEX + tx) * 3;
                row[0] = (unsigned char)((s[0] * sh) >> 8);
                row[1] = (unsigned char)((s[1] * sh) >> 8);
                row[2] = (unsigned char)((s[2] * sh) >> 8);
                row += 3;
                fx += stepX;
                fy += stepY;
            }
        }
    } else {
        for (y = 0; y < RH; y++) {
            unsigned char *row = TMP + (size_t)y * RW * 3;
            int v = (y < (int)horizon) ? 42 : 66;
            for (x = 0; x < RW; x++) { *row++ = (unsigned char)v; *row++ = (unsigned char)v;
                                       *row++ = (unsigned char)(v + 10); }
        }
    }

    /* ---- 2) 逐列 DDA 打墙, 贴纹理画竖条 ---- */
    for (x = 0; x < RW; x++) {
        float camX = DIRX[x] / tanf(0.5760f);      /* [-1,1] */
        float rdX = dirX + planeX * camX;
        float rdY = dirY + planeY * camX;
        int mapX = (int)floorf(px), mapY = (int)floorf(py);
        float ddx = (rdX == 0.0f) ? 1e30f : fabsf(1.0f / rdX);
        float ddy = (rdY == 0.0f) ? 1e30f : fabsf(1.0f / rdY);
        int stepX, stepY, side = 0, hit = 0, guard = 0;
        float sdx, sdy, perp, wallX;
        int lineH, y0, y1, texX, sh, yy;
        const unsigned char *tex;
        unsigned char *dp;

        if (rdX < 0) { stepX = -1; sdx = (px - mapX) * ddx; }
        else         { stepX = 1;  sdx = (mapX + 1 - px) * ddx; }
        if (rdY < 0) { stepY = -1; sdy = (py - mapY) * ddy; }
        else         { stepY = 1;  sdy = (mapY + 1 - py) * ddy; }

        while (!hit && guard++ < 512) {
            if (sdx < sdy) { sdx += ddx; mapX += stepX; side = 0; }
            else           { sdy += ddy; mapY += stepY; side = 1; }
            if (mapX < 0 || mapY < 0 || mapX >= MAPW || mapY >= MAPH) break;
            if (MAP[mapY * MAPW + mapX]) hit = 1;
        }
        if (!hit) { ZBUF[x] = 1e30f; continue; }

        perp = (side == 0) ? (sdx - ddx) : (sdy - ddy);
        if (perp < 0.02f) perp = 0.02f;
        ZBUF[x] = perp;

        lineH = (int)(FOCAL / perp);
        y0 = (int)(horizon - (1.0f - EYEH) * (float)lineH);
        y1 = (int)(horizon + EYEH * (float)lineH);
        if (y1 > y0) {
            texX = (int)(((side == 0) ? (py + perp * rdY) : (px + perp * rdX)) * TEX);
            texX &= (TEX - 1);
            /* 保证纹理方向和看到的面对应, 不然左右会镜像 */
            if ((side == 0 && rdX > 0) || (side == 1 && rdY < 0)) texX = TEX - 1 - texX;

            tex = TEXDATA[MAP[mapY * MAPW + mapX]];
            fog_k(perp, &sh);
            if (SHADE_SIDE && side == 1) sh = (sh * 3) >> 2;   /* 南北面压暗 */
            {
                int cy0 = y0 < 0 ? 0 : y0;
                int cy1 = y1 > RH ? RH : y1;
                float step = (float)TEX / (float)lineH;
                float texpos = (cy0 - horizon + (1.0f - EYEH) * (float)lineH) * step;
                dp = TMP + ((size_t)cy0 * RW + x) * 3;
                for (yy = cy0; yy < cy1; yy++) {
                    int ty = (int)texpos & (TEX - 1);
                    const unsigned char *s = tex + (ty * TEX + texX) * 3;
                    dp[0] = (unsigned char)((s[0] * sh) >> 8);
                    dp[1] = (unsigned char)((s[1] * sh) >> 8);
                    dp[2] = (unsigned char)((s[2] * sh) >> 8);
                    dp += RW * 3;
                    texpos += step;
                }
            }
        }
    }
}

void rc_render(unsigned char *out, float px, float py, float yaw, float pitch)
{
    render_core(px, py, yaw, pitch);
    upscale_to(out, OUTW * 3, 0);
}

void rc_render_bgr(unsigned char *fb, int stride, float px, float py,
                   float yaw, float pitch)
{
    render_core(px, py, yaw, pitch);
    upscale_to(fb, stride, 1);
}

/*=====================================================================
 *  碰撞: 圆形玩家 vs 网格墙。返回 1 可以走
 *===================================================================*/
int rc_can_move(float x, float y, float r)
{
    int x0, x1, y0, y1, i, j;
    if (!MAP) return 0;
    x0 = (int)floorf(x - r); x1 = (int)floorf(x + r);
    y0 = (int)floorf(y - r); y1 = (int)floorf(y + r);
    for (j = y0; j <= y1; j++) {
        for (i = x0; i <= x1; i++) {
            if (i < 0 || j < 0 || i >= MAPW || j >= MAPH) return 0;
            if (MAP[j * MAPW + i]) return 0;
        }
    }
    return 1;
}

unsigned char rc_cell(int x, int y)
{
    if (!MAP || x < 0 || y < 0 || x >= MAPW || y >= MAPH) return 1;
    return MAP[y * MAPW + x];
}

void rc_set_cell(int x, int y, unsigned char v)
{
    unsigned char *m = (unsigned char *)MAP;   /* 调用方保证可写 */
    if (!m || x < 0 || y < 0 || x >= MAPW || y >= MAPH) return;
    m[y * MAPW + x] = v;
}
