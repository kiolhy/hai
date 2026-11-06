# hai · UI 与逻辑优化方案（v3）

> 目标：让用户能**自己选择/切换要常驻的脚本并托管守护**；修掉所有不合理逻辑；UI 更清晰；实时数据用推送(SSE)。
> 参考 GitHub：DevControl-dashboard（Flask + SSE + 进程管控 + 端口/进程预览 + dashboard-owned PID 跟踪）、StayPresent（监控/自动重启/心跳存活、/status 面板）、kamalx06/ids-bachelor-thesis & moonlight16/hive（进程监督 + SSE 实时 + 重启计数 + systemd）。

## 一、体检发现的问题（按严重度）

**P0 功能/正确性**
1. **不能自己选择启动 / 无托管**：`/admin/script/start` 只 `subprocess.Popen` 盲目起脚本；不识别“外部已在运行的 farm_master”，点了会**重复起第二个**（同账号→会话/限频炸）；`RUNNING` 只在当前 worker 内存，app 重启即遗忘；无自动重启/开机自启。**根因**就是“无法选择并稳定托管一个常驻脚本”。
2. **数据重复入库**：文件桥接每 45s 无脑 INSERT，实测连续 3 条相同 `(752,100936,266)` → 历史库膨胀、趋势图台阶/噪声、长期会拖垮。
3. **桥接丢面板数据**：`collect_from_live_file` 的 payload 不含 plots/orders/tasks/thefts → 用桥接时看板「地块/订单/任务/被偷」面板是空的（不合理）。
4. **登录风暴**：无 live 文件时 collector 每轮 `login` ×4 重试，反复触发 `AUTH_SESSION_LIMIT`，且每次多一次会话/限频。

**P1 实时/体验**
5. `/live` 用 2s 轮询读整份 ws_status.json；应改 **SSE 推送**（省资源、近 0 延迟），也便于事件流。
6. 每个页面各写一份 header/CSS/导航 → 不一致、难维护；dashboard 有死代码（`(p.orders?null:null)` 等）；地块渲染依赖不存在字段。

**P2 运维/安全**
7. 历史库无**保留策略/清理**（85 条→每天约 2k 条，无上限）。
8. 生产用 Flask dev server；应以 gunicorn 单 worker（保证采集/守护线程唯一）；`SECURE_COOKIE` 需在 HTTPS 下开启。
9. 登录限流仅内存（重启清零）——可接受但可加持久化/告警。

## 二、优化方案

### A. 常驻脚本“可选择 + 托管守护”（解决 P0-1，核心）
- 新增 `settings(resident_script, resident_autostart)` 配置（SQLite）。
- 应用内置 **Supervisor 线程**：每 ~10s 检查所选常驻脚本；未运行且“非外部日志新鲜运行”则按 `autostart` 自动拉起；崩溃自动重启；**同一时刻只允许一个常驻**（切换=先停旧再起新）。
- **外部进程识别**：以“日志 180s 内更新”判定外部已在跑 → 拒绝重复起（返回“外部已在运行，pid=…”），避免双开。
- `/api/scripts` 增加 `resident`、`autostart`、`managed_pid`；`/scripts` 页每行加「设为常驻/取消常驻」按钮 + 顶部当前常驻状态。
- 端点：`POST /admin/resident {script, autostart}`。

### B. 数据层优化（P0-2/3，P2-7）
- 文件桥接**去重**：与上一条比较 `level/levelProgress/stars/coins/steals_total/steal_today`，**变化才入库**；未变化每 `RETAIN_UNCHANGED`(=300s) 才补一条心跳点（保趋势连续又不过量）。
- 桥接**富 payload**：farm_master 的 `farm_live.json` 增写 `plots / orders / tasks / mature / neighbors`；看板换成完整数据。
- **保留策略**：后台定期 `DELETE` 超出 `SNAP_KEEP`(=8000) 或早于 `SNAP_DAYS`(=14d) 的旧快照；`PRAGMA`/索引优化 ts。

### C. 实时推送（P1-5）
- 新增 `GET /api/live/stream`（SSE）：服务端读 `ws_status.json`，变更即 `data:` 推送事件(type=状态/帧)；前端 `EventSource` 订阅，秒级刷新、断线自动重连；保留 `/api/live` 作为兜底。

### D. UI 优化（P1-6）
- 统一导航与配色（抽出 `_nav` 片段/基础样式，四页一致：看板/实时动态/脚本监控/后台/退出）。
- 修 dashboard 死代码；地块用 payload.plots 正确渲染（成熟/生长中/空）；图表空态与错误提示。
- `/scripts`：类型徽标(常驻/工具/旧版) + 常驻空闲红字 + **常驻选择**交互。
- 方案与“不合理处”均在此文档留档。

### E. 运维/安全（P2-8/9）
- Docker/gunicorn **单 worker**（确保线程唯一）；`SECURE_COOKIE=1`+HTTPS；`/healthz` 增细节。
- 建议 systemd 托管 app 本体（hive 做法）。

## 三、实施清单
- [本轮] A 常驻选择+Supervisor；B 去重/富payload/保留策略；C SSE；D 导航一致+修 dashboard+scripts 常驻选择；文档。
- [后续] 持久化限流、Prometheus/健康细节、事件中文可读化、移动端细节。

## 四、验收
1. 在 `/scripts` 能“设为常驻”任一脚本并看到它被托管运行、崩溃自动重启、切换互斥；外部已在跑时拒绝重复。
2. 连续观察 DB：同值不再刷屏，仅在变化/心跳时增长；`/api/history` 曲线平滑。
3. 桥接模式下看板地块/订单/任务/被偷面板有数据。
4. `/live` 用 EventSource 推送，无 2s 轮询。
5. 四页导航一致、无报错、无死代码。
