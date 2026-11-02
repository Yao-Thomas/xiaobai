# 部署与实机验收（阶段9 / 阶段10 交付物）

生成时间: 2026-10-10 18:35:15

## 阶段9 分级部署

### 第一次：只更新 PS/UI（**已完成**）
- 只替换 `/home/zynq/ui/` 下 5 个文件，**不停/起任何服务**（AGENTS.md 规则6）
- 板端与本地哈希已逐个校验一致
- 验证过：在旧 bitstream 上能**优雅回退**（能力检测报"不可用" -> 走 C 回退，不崩）

### 第二次：更新 FPGA（**待授权**）

阻塞点: `/mnt/boot` 已满（约 12 个历史 4MB 备份占满）
-> 需要先删掉几个旧备份腾出至少 4MB。

腾出空间后执行:
```
python flash_fpga.py            # 演练：只检查 + 备份，不安装不重启
python flash_fpga.py --apply    # 真跑：备份 -> 安装 -> 重启 -> 验证
```

脚本内置:
- 自动备份旧 bit 到 `/mnt/boot/system.bit.bak_<时间戳>`
- md5 校验后才安装
- 重启后自动验证 FPGA 路径是否生效
- 失败时打印回滚命令

**串口回滚**（SSH 完全不通用这条）:
```
python uboot_recover2.py     # 打断 u-boot 倒计时，从 RAM 启动旧 bit
```

## 阶段10 实机验收指标

| 项目 | 目标 | 测量方法 |
|---|---|---|
| 波形帧率 | >= 25 FPS | UI 顶栏 FPS / `top` |
| 触摸响应 P95 | < 60 ms | 注入触摸并计时（`fbui.Touch` 支持 move） |
| 通道切换 | < 100 ms | 点通道弹层到画面更新 |
| 模式切换 | < 150 ms | 同理 |
| ARM 单核占用 | < 35% | `awk '/proc/<pid>/stat'` 差 5 秒 / CLK_TCK |
| 双核总体 | < 25% | `/proc/loadavg` + top |
| Normal 无触发 | UI 不阻塞 | `sd_capture()` 返回时间（已实测 0.3~0.8 ms） |
| Auto 不出现边沿选择 | 是 | 模式弹层只有 Auto/Normal/Single + 确定 |
| 50us/div | 窗口 = 500us | `Timebase(9).actual_tdiv*10` |
| ADC 过量程 | 明确提示 | 故意超 ±5V，看顶栏红色告警 |
| 双通道 | 可同时勾选 | 通道弹层两个复选 + 确定 |
| CNN 资源 | 64 DSP 完整保留 | `report_utilization` |
| 连续运行 | 2 小时无卡死 | 长跑 + 周期性截图比对 |

## 已在本轮验证过的指标（板端实测）

| 项目 | 实测 | 结论 |
|---|---|---|
| Normal 无触发 capture() | **0.8 ms**（旧版 4000 ms） | **PASS** |
| 时基窗口 50us/div | **500us** | **PASS** |
| FPGA 路径判定（旧 bit） | 正确报不可用 -> 回退 | **PASS** |
| AUTO 未锁定 | 档位不变 | **PASS** |
| AUTO 10Vpp | 2.5V/div，占屏 **50.0%** | **PASS** |
| C 回退读一帧 | 6.88 ms | 参考 |
| 时序 | TIMING_MET=1 | **PASS** |
| CNN 预算 | LUT 20146/43200, BRAM 10/100, DSP 2/156 | **PASS** |

## 尚未验证（等新 bit 上板）

- FPGA 路径的实际 FPS / CPU 占用
- 触摸响应 P95
- 通道/模式切换耗时
- 过量程告警（需要把信号源故意调超 ±5V）
- 连续 2 小时
