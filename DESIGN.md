# hai · 设计方案（v2：鉴权 + 网页配置 + 全量数据看板）

## 1. 目标
把 `hai` 从"只读看板"升级为**可部署的完整站点**：
1. **访问需登录**：进站先输入访问密码，登录后才能看任何数据（严格鉴权）。
2. **农场账号在网页输入**：管理员在后台填 `用户名/密码`，服务端加密保存，不再写死环境变量。
3. **管理后台**：改访问密码、设置/更新农场账号、查看采集状态、手动采集。
4. **全量数据面板 + 趋势图**：等级/经验、钻石、金币、**偷菜统计（我偷次数、今日偷、被偷记录、偷菜流水）**、收获、订单、地块、邻居可偷等，全部带时间趋势。
5. **打包**：Docker/zip，推到 `github.com/kiolhy/hai`。

## 2. 架构
```
浏览器 ──HTTPS──> Flask(app.py)
                    ├─ 鉴权层: 会话Cookie(HttpOnly) + 访问密码(PBKDF2哈希) + CSRF + 登录限流
                    ├─ 管理后台 /admin: 改密 / 设农场账号(Fernet加密) / 采集状态
                    ├─ REST API(/api/*, 需登录): latest/history/steal/status
                    ├─ 采集器线程: 解密农场账号→登录农场→拉 state/neighbors/log/thefts→写SQLite
                    └─ SQLite(data/history.db): account / settings / snapshots / steal_events
```

## 3. 严格鉴权设计
- **访问密码（单管理员）**：`werkzeug.security` PBKDF2-SHA256 哈希存库；**首次访问引导设置**（不写死）。
- **会话**：Flask 签名 Cookie（`SECRET_KEY` 随机生成存 `data/secret.key`，不入库）；`HttpOnly`、`SameSite=Lax`；生产 `Secure`。
- **CSRF**：会话级 token，所有 POST 表单/接口校验。
- **登录限流**：按 IP 统计失败次数，5 次/5 分钟锁 5 分钟。
- **密码策略**：最少 8 位，改密需旧密码；改密后失效所有会话（旋转 session 版本号）。
- **农场凭据加密**：`cryptography.Fernet`，密钥 `data/fernet.key`（gitignore）；数据库只存密文。

## 4. 数据模型（SQLite）
- `account(id=1, pass_hash, sess_ver, created)`
- `settings(k,v)`（如 site_name）
- `farm_creds(enc_username, enc_password, updated)`（Fernet 密文）
- `snapshots(ts, level, levelProgress, levelRequired, stars, coins,
   steals_total, steal_today, thefts_today, harvests, planted, sold, orders_done,
   plots_count, mature_count, neighbors, qq_neighbors, harvest_stars, order_stars, payload_json)`
- `steal_events(ts, kind, thief_id, victim_id, amount, detail_json)`（kind=stolen_by_me / stolen_from_me / attempt）
- 另有 `thefts`（从 /farm/thefts 采集：谁偷我）与 `log`（/farm/log 中 qqSteal* 动作）

## 5. 数据面板与趋势
- 顶部卡片：等级/经验、钻石、金币、**累计偷菜/今日偷菜**、**今日被偷**、邻居可偷、地块(成熟/总)。
- 趋势图（Chart.js，多序列）：① 钻石&金币 ② 经验等级 ③ **偷菜：今日偷/被偷 次数** ④ 收获&订单。
- 面板：地块网格、**偷菜流水表**（recent qqSteal*, stolen/blocked/skipped）、**被偷记录表**（thief_id/amount/时间）、订单、丰收任务、采集状态。
- 自动刷新 30s；时间窗可选（24h/7d/全部）。

## 6. 页面/路由
- `GET /setup`（首次设访问密码）→ `POST /setup`
- `GET/POST /login`、`POST /logout`
- `GET /`（看板，需登录）
- `GET /admin`（后台，需登录）; `POST /admin/password`、`POST /admin/farm`、`POST /admin/collect`
- `GET /api/latest|history|steal|status`（需登录，JSON）
- `GET /healthz`（无鉴权）
- `GET/POST /api/farm/...` 不对公网暴露；采集走服务端登录。

## 7. 采集器
每 `COLLECT_INTERVAL`（默认120s）：
登录农场(用解密凭据)+刷新token → 拉 state/neighbors/log/thefts →
解析出上面指标 → 写 snapshots + steal_events；失败记录 last_error 并退避。

## 8. 打包与部署
- `Dockerfile`(gunicorn) + `docker-compose.yml` + `.env.example`；`data/` 挂卷持久化。
- `pack.sh`/zip 打包整个项目（排除 data 密文、__pycache__、.git）。
- `git` 提交并 push 到 `github.com/kiolhy/hai`。

## 9. 安全清单
- 无明文密码入库；密钥/密文/DB 均 gitignore；生产强制 HTTPS + Secure Cookie；登录限流+CSRF；错误不回显敏感信息。

## 10. 里程碑（执行）
1) 重写 `app.py`（鉴权+后台+加密凭据+扩展采集）  2) 前端 login/setup/admin/dashboard  3) 本地端到端测试  4) 打包 + push。
