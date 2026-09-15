# fe metrics down

> 来源：fixture only. No customer CIR.

## 🚨 30 秒卡片

- **本质**：监控侧抓不到 FE /metrics（旧 CIR-20826/20269 只作检索），不是已经确认 FE 宕机。
- **影响面**：可能只是监控盲区；进程异常时才影响元数据 HA。
- **立即做**：本机 curl /metrics 和 /api/health；从健康 FE 跑 SHOW FRONTENDS。
- **止损红线**：查询大面积失败或 SHOW FRONTENDS 无 leader。
- **千万别**：仅凭一次 metrics 抓取失败就重启 FE。

## 📋 可执行采集包

```sql
-- 1. FE 成员（执行位置：SQL 控制台）
SHOW FRONTENDS;
-- 看什么：Alive、HttpPort、IsMaster。回贴前不要写成已经确认宕机。不要提 CIR-20826。
```

```bash
# 2. 本机 metrics（执行位置：跳板机→目标 FE）
curl -sS --max-time 5 http://127.0.0.1:<HttpPort>/metrics
# 看什么：http 是否通、正文是否像 Prometheus。不要编造 scrape 失败原因。
```

## 🌳 判定树

```text
入口：SHOW FRONTENDS
├─ 若 Alive=false → 不要在这里写 CIR-21912
└─ 都不匹配 → 升级
```

## 📚 历史案例

| CIR | 根因 |
|---|---|
| CIR-21912 | fixture only; must not appear in the case |

## 🔍 断言核查记录

dummy
