# 板端可行性结论（模型① 量化）

- 模型：merged（494.0M 参数）
- INT4 量化体积（含 group scale）：**250.3 MB**
- INT8 量化体积（含 scale）：472.8 MB
- 分析式估算：bf16=942 MB，int4≈243 MB

## 实测数字（由 quantize_llm.py 运行回填）

| 项 | 值 |
|---|---|
| GPU peak 显存 | 2839.4 MB |
| 进程 peak RSS | 42839.1 MB |
| 进程 RSS | 3360.4 MB |
| 16-token 前向延迟 | 691.0 ms |
| INT8 相对 MSE | 9.685e-05 |
| INT4 相对 MSE | 1.652e-02 |

## 结论

0.5B 模型 INT4 权重约 250 MB，而板端 1 GB RAM 扣除系统基线（约 600 MB）后仅剩约 424 MB。加上 transformers/Python 运行时、KV cache、激活内存，几乎必然 OOM。
⇒ **明确结论：板端直接加载 0.5B INT4 不可靠，走云端，板子只做转发；本地用纯标准库 RAG（几十 MB）做离线降级。**

> 补充：即使 INT4 权重只有 ~250 MB，真正上板还要叠加：
> ① transformers 库 + Python 解释器本身（数百 MB）② KV cache 与激活③ tokenizer/embedding 常保留高精度。三者相加在 1 GB 板上没有余量。
