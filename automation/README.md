# automation/ — 农场自动化任务脚本（全部可被看板监控）

这些是从作业目录归档进来的任务脚本。看板左侧「📜 脚本监控」(`/scripts`) 会列出本目录下所有 `.py`，
显示运行状态、日志更新时间与最近日志，并可一键 **启动/停止**（`/admin/script/<start|stop>/<name>`）。

## 脚本清单
- `farm_master.py` — 主守护：种菜/收获/卖/领奖/花金币 + **多线程偷菜(邻居+全站扫描)**（并发）。
- `ws_play.py` — WebSocket 玩法：careAll(水/草/虫)、工坊/商会尝试、并发偷菜。
- `harvest_all.py` / `mature_all.py` / `play_all.py` — 高频收割/催熟/全玩法扫描。
- `steal_all.py` / `steal_v3.py` / `hunt_all.py` / `scan_all.py` / `rescan*.py` / `tail_scan.py` — 邻居与全站偷菜/扫描。
- `auto_farm.py` / `farm_loop.py` — 早期农场循环。
- `do_action.py` — 通用动作执行器（409 重试）。
- `spend_coins.py` — 金币消费(化肥/补给包)实测。
- `redeem.py` — 钻石→余额（受限，仅记录）。
- `final_sweep.py` — 收尾清扫。
- `enable_guardian.py` — 看家护院（购买犬舍/守护犬并上岗）。

## 配置
多数脚本从以下来源读取账号/会话，**不含明文密钥**：
- 环境变量：`FARM_BASE`、`FARM_USER`、`FARM_PW`；
- 或读取本机 `_recon/mycookie_*.txt`、`jar_*.txt` 会话文件（部署时按需调整路径）。

看板“启动”按钮以 `python -u <脚本>` 在本目录运行，需在服务进程环境里提供上述变量；
外部自行启动的脚本也会被监控（按日志 3 分钟内有更新判定为运行中）。日志目录由 `SCRIPTS_LOG_DIR` 指定。

## 看家护院 / 防被偷 说明
- 本 NewAPI 部署对 `buyDog/buyKennel/setGuardDog` 返回 `QQ action is not connected`（与商会/工坊同类，模块未接通），**守护犬当前无法启用**。
- 可行的防被偷手段 = **成熟即收**：`farm_master.py` 每轮先收获成熟地块，压缩“成熟→收获”的暴露窗口，减少被邻居偷取。
- 看板「被偷记录」面板持续展示谁在偷、偷了多少，便于评估。

## 实时数据桥接（farm_live.json）
- farm_master 每次取 state 成功即写 results/farm_live.json
- 看板设 FARM_LIVE_JSON 指向该文件，优先读文件入库（无需登录/不占会话/不受限频）
- 示例：FARM_LIVE_JSON=../results/farm_live.json COLLECT_INTERVAL=45 python app.py
