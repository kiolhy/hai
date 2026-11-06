# hai

> 百川农场（NewAPI 扩展）· 服务端数据看板 + 采集器。部署在服务器上，随时查看账号各种数据。

## 它是什么
`hai` 是一个自包含的轻量服务：
- **采集器**：用你的农场账号（NewAPI）登录，定时拉取 `/api/farm2d/farm/state`、`/farm/neighbors`，
  写入本地 SQLite 历史库。
- **数据看板**：Web 页面实时展示 —— 等级/经验、钻石、金币、地块状态、可偷邻居数、订单委托、丰收任务，
  以及钻石/金币的历史曲线。
- **REST API**：`/api/latest`、`/api/history`、`/api/status`、`/api/collect`、`/healthz`，方便二次集成。

## 目录结构
```
hai/
├── app.py               # Flask 服务 + 采集线程 + REST API
├── static/index.html    # 数据看板前端（Chart.js）
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── data/               # 运行时生成的 SQLite 历史库（不入库）
```

## 配置（环境变量）
| 变量 | 说明 | 默认 |
|---|---|---|
| `FARM_BASE` | 农场站点根地址 | `https://www.0809.one` |
| `FARM_USERNAME` | 农场账号用户名 | 空 |
| `FARM_PASSWORD` | 农场账号密码 | 空 |
| `PORT` | 监听端口 | `8080` |
| `COLLECT_INTERVAL` | 采集间隔（秒） | `300` |
| `DB_PATH` | SQLite 路径 | `data/history.db` |

> 未配置账号时，服务照常启动，仅展示历史数据并在状态里提示"未配置"。

## 快速开始（本机 / 服务器）
```bash
pip install -r requirements.txt
export FARM_USERNAME=你的账号
export FARM_PASSWORD=你的密码
python app.py
# 浏览器打开 http://<服务器IP>:8080
```

## Docker 部署
```bash
cp .env.example .env   # 填写账号密码
docker compose up -d --build
# 访问 http://<服务器IP>:8080
```

## systemd（裸机）
```ini
# /etc/systemd/system/hai.service
[Unit]
Description=hai farm dashboard
After=network.target
[Service]
WorkingDirectory=/opt/hai
Environment=FARM_BASE=https://www.0809.one
Environment=FARM_USERNAME=your_username
Environment=FARM_PASSWORD=your_password
ExecStart=/usr/bin/python3 app.py
Restart=always
[Install]
WantedBy=multi-user.target
```
```bash
systemctl daemon-reload && systemctl enable --now hai
```

## API
- `GET /api/status` → 配置与采集状态
- `GET /api/latest` → 最新一条快照（等级/经验/钻石/金币/地块/订单/任务/邻居）
- `GET /api/history?limit=300` → 历史时间序列（用于曲线）
- `POST /api/collect` → 立即采集一次
- `GET /healthz` → 健康检查

## 安全说明
- 账号密码只经环境变量注入，不入库、不写死进代码；`.env` 与 `data/*.db` 已在 `.gitignore` 中排除。
- 采集仅使用官方同源接口（登录 / 刷新 token / 农场只读接口），不修改游戏数据。

## License
MIT

# hai

## v2 更新（鉴权 + 网页配置 + 全量面板）
- 进站需访问密码：首次访问 /setup 设置，之后 /login 登录；PBKDF2 哈希 + 会话 + CSRF + 登录限流。
- 农场账号在 /admin 网页输入，Fernet 加密存储（不再写死环境变量）。
- 后台 /admin：改访问密码、设农场账号、手动采集、查看状态。
- 看板：等级/经验/钻石/金币、偷菜（累计/今日/趋势/流水/被偷记录）、收获/订单趋势、地块。
- 方案见 DESIGN.md。
