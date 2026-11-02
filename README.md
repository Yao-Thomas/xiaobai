# 小白智枢 · FPGA 智能工程终端

> **Xiaobai: An FPGA–AI Intelligent Engineering Terminal**
> 2026 全国大学生嵌入式芯片与系统设计竞赛 · AMD 赛道 · 初级组
> 队伍：豆包说的队（47602） · 福州大学

基于 **AMD Xilinx ZYNQ-7020** 的边缘 AI 智能示波器与工程助手：在 FPGA 逻辑里完成双通道采集与
INT8 卷积网络推理，在 ARM Linux 上运行桌面系统与 AI Agent，并支持云端多模态模型二次诊断。

---

## 核心特性

| 能力 | 说明 |
|---|---|
| **双通道采集** | PL 侧 20 MS/s、4096 点深度、10 bit，硬件触发与抽取 |
| **边缘 AI 识别** | 9 类 INT8 CNN 硬件加速器，权重仅 4.5 KB，单次推理 20~25 ms，无需联网 |
| **12 类波形模板在线学习** | 谐波签名（6 维）+ 包络特征（64 维），现场摆一种新波形 10 秒内学会，不用重训、不用重烧 |
| **云边协同** | 本地识别为主结论，云端多模态（16 类）+ 大模型仅作参考补充 |
| **板载 AI Agent** | 键盘 / 语音 / 手写三种输入，可执行板载命令与硬件操作 |
| **完整桌面** | 4 页 25 个板载应用（示波器、音乐、文件、设置、健康监测…） |
| **11 个自研 FPGA IP** | 采集、CNN 卷积、CNN 全连接、GPU 波形渲染、I2S 音频、VTC 视频时序、PWM 背光等 |

## 硬件平台

```
板卡：正点原子 领航者 ZYNQ7020 V3.9（xc7z020clg400-2）
系统：Ubuntu 20.04 armv7l / Linux 5.4.0-xilinx-v2020.2
显示：LCD 1024×600，双缓冲 framebuffer
音频：ES8388 + MD8002A，双路独立输出（Output1 耳机 / Output2 板载喇叭）
采集：双路高速 AD 模块（PL 实跑 20 MS/s，4096 深度，10 bit）
```

## 目录说明

```
ui/                板端桌面与全部应用（Python）
  wave_templates.py      ★ 12 类波形识别引擎
  apps_scope_dual.py     ★ 双通道示波器 + AI 分析卡片
  apps_agent.py          ★ 系统管家小白（键盘/语音/手写）
  scope_dual.c           ★ 波形绘制与包络折线 C 加速库
  audio_alsa_svc.py       ES8388 音频服务
agent/             Agent 服务（LLM 后端、工具层、TTS/ASR、语音回路）
cloud_api.py       板端云 API（Web/PC 客户端接入）
infer_local.py     本地 CNN 推理
wave_weights.bin   量化权重（4.5 KB）
wave_model_spec.json  网络结构规格
xb_chat.py         PC 客户端（聊天 + 云协同示波器）
scope_panel.py     PC 云协同示波器面板
build_code_pkg.py  一键组装完整代码包（含板端拉取 + RAR 打包）
```

## 快速开始

### 板端
```bash
# 1. 放入板子上对应目录
scp ui/*.py zynq@<board>:~/ui/
scp agent/*.py zynq@<board>:~/agent/
scp infer_local.py wave_weights.bin wave_model_spec.json zynq@<board>:~/

# 2. 编译 C 加速库（板端）
cd ~/ui && gcc -O2 -shared -fPIC -o libscopedual.so scope_dual.c

# 3. 服务
sudo systemctl daemon-reload
sudo systemctl restart zynq-desktop zynq-agent zynq-audio cloud-api
```

### PC 端
```bash
pip install -r requirements.txt      # numpy, pillow
python xb_chat.py                    # 启动客户端（设置里填板子 IP 与 token）
python -m wave_ai.serve --port 8000  # 云端多模态服务（可选）
```

## 实测数据

```
板上 9 类 CNN 留出集准确率          95.64%
单次识别耗时（PL 推理 + 分类）       20~25 ms
调幅波在不同时基档位识别            16/16 全通过
新波形现场学习后连续识别             8/8 稳定
服务自动发现（板→PC 8000）          0.4~1.3 s
```

## 安全说明

- 仓库中所有 API Key 已替换为占位符（`YOUR_*_KEY_HERE`），运行时通过环境变量或
  `/etc/zynq-baidu.env` 等外部配置注入。
- 板端令牌、Wi-Fi 口令等本机配置不纳入版本控制（见 `.gitignore`）。

## 许可

本项目为竞赛作品，代码仅供学习与评审参考。第三方组件遵循其各自许可。
