#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""repack_handover.py —— 重打两份交接包

════════════════════════════════════════════════════════════════════
为什么需要它
════════════════════════════════════════════════════════════════════
交接包（桌面上的 AI训练交接包.zip / 示波器交接包.zip）是 2026-09-30 打的，
之后主线侧改了很多东西：

    · 06_分工总表：CNN 从"预留"变成"已实现"（含寄存器偏移表）
    · 10_云协同接口约定单 v1.0（新写的）
    · 11_主线融合侧_进度与交接状态（新写的）
    · 12_云协同客户端_EXE_APK打包指南（新写的）
    · 03/05/08 的地址表也更新了

不重打的话，队友拿到的还是旧信息 —— 尤其 CNN 地址和云协同接口。

════════════════════════════════════════════════════════════════════
它做什么
════════════════════════════════════════════════════════════════════
    ① 把【主目录里的最新文档】同步到 _build/<包>/ 下的对应位置
    ② 把新写的文档也塞进去
    ③ 重新打 zip 到桌面
    ④ 打印每个包的文件数和大小，方便核对

★ 只同步文档，不动二进制（工程/截图那些）。

用法:
    python repack_handover.py            # 同步 + 打包
    python repack_handover.py --dry      # 只看会改什么
"""
import argparse
import os
import shutil
import sys
import zipfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PKG_ROOT = r"D:\总文件夹\FPGA2026_项目交接包"
SUB = os.path.join(PKG_ROOT, "16_分工与任务")
BUILD = os.path.join(SUB, "_build")
DESKTOP = os.path.join(os.path.expanduser("~"), "Desktop")

# ★ 文档映射：(主目录里的文件, 在包里的相对路径)
#   两个包都要一份（任务书 + 接口规则）
COMMON = [
    ("06_分工总表_核对版.md",      "01_任务书/06_分工总表_核对版.md"),
    ("01_功能清单.md",             "01_任务书/01_功能清单.md"),
    ("02_详细任务分解.md",         "01_任务书/02_详细任务分解.md"),
    ("07_接口约定单.md",           "02_接口与规则/07_接口约定单.md"),
    ("08_协作规则.md",             "02_接口与规则/08_协作规则.md"),
    ("09_板子与工具链.md",         "02_接口与规则/09_板子与工具链.md"),
    ("10_云协同接口约定单.md",     "02_接口与规则/10_云协同接口约定单.md"),
    ("11_主线融合侧_进度与交接状态.md", "02_接口与规则/11_主线融合侧_进度与交接状态.md"),
    ("12_云协同客户端_EXE_APK打包指南.md", "02_接口与规则/12_云协同客户端_EXE_APK打包指南.md"),
]

# 各包专属
OWN = {
    "AI训练交接包": [
        ("04_分工_AI训练负责人.md", "01_任务书/04_分工_AI训练负责人.md"),
    ],
    "示波器交接包": [
        ("03_分工_示波器负责人.md", "01_任务书/03_分工_示波器负责人.md"),
    ],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    print("=" * 74)
    print(" 重打交接包")
    print("=" * 74)
    print(" 源: %s" % SUB)
    print(" 目标: %s" % DESKTOP)
    if a.dry:
        print(" ★ --dry：只看会改什么")
    print()

    total_updated = 0

    for pkg in ("AI训练交接包", "示波器交接包"):
        pdir = os.path.join(BUILD, pkg)
        if not os.path.isdir(pdir):
            print("★ 找不到 %s" % pdir)
            continue
        print("【%s】" % pkg)
        n = 0
        for src_name, rel in COMMON + OWN.get(pkg, []):
            src = os.path.join(SUB, src_name)
            dst = os.path.join(pdir, rel.replace("/", os.sep))
            if not os.path.exists(src):
                print("   ✗ 源不存在：%s" % src_name)
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            # ★ 只在内容不同的时候才拷（免得把时间戳全刷了）
            same = False
            if os.path.exists(dst):
                try:
                    same = (os.path.getsize(src) == os.path.getsize(dst))
                except Exception:
                    same = False
            if same:
                print("   - %-44s （已是最新）" % rel)
                continue
            if not a.dry:
                shutil.copy2(src, dst)
            print("   ✓ %-44s -> %s" % (rel, pkg))
            n += 1
        print("   更新 %d 个文件" % n)
        total_updated += n
        print()

    if a.dry:
        print("★ --dry：一共会更新 %d 个文件" % total_updated)
        return 0

    # ── 打包 ──
    print("【打包】")
    for pkg in ("AI训练交接包", "示波器交接包"):
        pdir = os.path.join(BUILD, pkg)
        if not os.path.isdir(pdir):
            continue
        zpath = os.path.join(DESKTOP, pkg + ".zip")
        if os.path.exists(zpath):
            try:
                os.remove(zpath)
            except Exception as e:
                print("   ✗ 删不掉旧 zip: %s" % e)
                continue
        cnt = 0
        try:
            with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED,
                                 compresslevel=6) as z:
                for root, dirs, files in os.walk(pdir):
                    for f in files:
                        fp = os.path.join(root, f)
                        arc = os.path.relpath(fp, pdir)
                        z.write(fp, arc)
                        cnt += 1
        except Exception as e:
            print("   ✗ 打包失败: %s" % e)
            continue
        mb = os.path.getsize(zpath) / 1048576.0
        print("   ✓ %-22s %3d 个文件  %6.1f MB" % (pkg + ".zip", cnt, mb))

    print()
    print("=" * 74)
    print(" 完成。一共同步了 %d 个文档。" % total_updated)
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
