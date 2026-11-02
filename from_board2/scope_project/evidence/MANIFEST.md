# release_candidate 清单

时间: 2026-10-10 18:35:15

| 文件 | md5 | 字节 |
|---|---|---|
| AXI_REGISTER_MAP.md | `9ce454a567ce96e7e35ed3662466cdba` | 4331 |
| CNN_RESOURCE_BUDGET.md | `1053ed6ed455380d27b7c1d84be8c34f` | 2670 |
| DEPLOY_AND_ACCEPTANCE.md | `83f010fc88c09d26b6cf80ae76f05a17` | 2813 |

## 板上 PS 文件（已校验一致）

| 文件 | md5 |
|---|---|
| apps_scope_dual.py | `57e3004c194d5904f6f32070c79efa90` |
| scope_dual.py | `bc0fc7060a74ec1938e9290946c23f6a` |
| scope_model.py | `84a5f50a2e85ebd6658d8e1326a91053` |
| scope_processing.py | `d8f19d41f4f4c74799dc0e6aa868f24b` |

## bitstream

| 对象 | md5 | 说明 |
|---|---|---|
| 新（已构建，未烧写） | `c5ef18c2d0ee4c7b3e2aed00eddce78f` | out/system_scope_dual.bit, TIMING_MET=1 |
| 板端当前 | `f3d464c9a3a120d08196bdc11f913995` | 旧版，FPGA 下放未生效 |