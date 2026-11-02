/*
 * fbbridge.c —— 把 Xvfb 的帧缓冲桥接到 /dev/fb0 (支持缩放到任意分辨率)
 *
 * 为什么需要它:
 *   Ubuntu 的 Minetest 用 Irrlicht 的 X11 后端, 非要 X server; 而这块板子的
 *   X (fbdev/modesetting) 起不来。所以用 Xvfb 起虚拟 X, 再把它 `-fbdir`
 *   生成的实时帧缓冲搬到真实 LCD 上。
 *
 *   Xvfb fbdir 文件格式是 XWD:
 *     [XWD 头 header_size 字节] [ncolors*12 字节调色板] [像素数据]
 *     32bpp, 像素顺序 (LE) = B G R X
 *
 *   本程序把 Xvfb 的分辨率【最近邻放大】到 LCD 的 1024x600,
 *   这样可以让 Minetest 在 512x300 / 256x150 等低分辨率下渲染,
 *   大幅提升帧率, 再由这里补到全屏。
 *
 * 编译: gcc -O2 -o fbbridge fbbridge.c
 * 用法: ./fbbridge [-r 帧率] [-s Xvfb文件] [-f /dev/fb0] [-v]
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/mman.h>
#include <sys/stat.h>

static const char *XVFB_FILE = "/tmp/Xvfb_screen0";
static const char *FB_DEV    = "/dev/fb0";
static int FB_W = 1024, FB_H = 600;   /* LCD 分辨率, 固定 */
static int TARGET_FPS = 30;
static int VERBOSE = 0;

static uint32_t be32(const uint8_t *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
           ((uint32_t)p[2] << 8) | (uint32_t)p[3];
}

int main(int argc, char **argv) {
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-s") && i + 1 < argc) XVFB_FILE = argv[++i];
        else if (!strcmp(argv[i], "-f") && i + 1 < argc) FB_DEV = argv[++i];
        else if (!strcmp(argv[i], "-r") && i + 1 < argc) TARGET_FPS = atoi(argv[++i]);
        else if (!strcmp(argv[i], "-v")) VERBOSE = 1;
    }

    const size_t fb_size = (size_t)FB_W * FB_H * 3;
    int fbfd = open(FB_DEV, O_RDWR);
    if (fbfd < 0) { fprintf(stderr, "open %s: %s\n", FB_DEV, strerror(errno)); return 1; }
    uint8_t *fb = mmap(NULL, fb_size, PROT_READ | PROT_WRITE, MAP_SHARED, fbfd, 0);
    if (fb == MAP_FAILED) { perror("mmap fb"); return 1; }
    if (VERBOSE) fprintf(stderr, "[fbbridge] LCD %dx%d 已映射\n", FB_W, FB_H);

    uint8_t *prev = calloc(fb_size, 1);

    /* X -> LCD 的横向映射表 (最近邻) */
    int32_t xmap[4096];
    for (int i = 0; i < 4096; i++) xmap[i] = 0;

    int    last_w = -1, last_h = -1;
    long   frames = 0, updates = 0;
    double sum_copy_ms = 0;

    for (;;) {
        int ffd = open(XVFB_FILE, O_RDONLY);
        if (ffd < 0) { usleep(200000); continue; }
        struct stat st;
        if (fstat(ffd, &st) < 0 || st.st_size < 4096) { close(ffd); usleep(200000); continue; }

        size_t src_size = st.st_size;
        uint8_t *src = mmap(NULL, src_size, PROT_READ, MAP_SHARED, ffd, 0);
        if (src == MAP_FAILED) { close(ffd); usleep(200000); continue; }

        uint32_t hsz = be32(src + 0);
        uint32_t bpp = be32(src + 44);
        uint32_t bpl = be32(src + 48);
        uint32_t ncol = be32(src + 76);
        uint32_t sw = be32(src + 16), sh = be32(src + 20);
        size_t off = hsz + (size_t)ncol * 12;

        if (bpp == 32 && sw > 0 && sh > 0 && sw <= 4096 &&
            off + (size_t)bpl * sh <= src_size) {
            if ((int)sw != last_w) {
                for (int i = 0; i < 4096; i++)
                    xmap[i] = (int)((long)i * sw / FB_W);
                last_w = sw;
                if (VERBOSE) fprintf(stderr, "[fbbridge] 源分辨率 %ux%u -> 放大到 %dx%d\n",
                                     sw, sh, FB_W, FB_H);
            }
            if ((int)sh != last_h) last_h = sh;

            const uint8_t *s = src + off;
            for (int y = 0; y < FB_H; y++) {
                int sy = (int)((long)y * sh / FB_H);
                const uint8_t *sp = s + (size_t)sy * bpl;
                uint8_t *dp = fb + (size_t)y * FB_W * 3;
                for (int x = 0; x < FB_W; x++) {
                    const uint8_t *p = sp + xmap[x] * 4;
                    dp[x*3+0] = p[0];
                    dp[x*3+1] = p[1];
                    dp[x*3+2] = p[2];
                }
            }

            if (memcmp(fb, prev, fb_size) != 0) {
                memcpy(prev, fb, fb_size);
                updates++;
            }
        }
        munmap(src, src_size);
        close(ffd);

        frames++;
        if (VERBOSE && frames % 150 == 0)
            fprintf(stderr, "[fbbridge] %ld 帧, %ld 次新画面, 平均拷贝 %.1f ms\n",
                    frames, updates, sum_copy_ms / (frames ? frames : 1));
        if (TARGET_FPS > 0) usleep(1000000 / TARGET_FPS);
    }
    return 0;
}
