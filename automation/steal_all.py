#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
百川农场 (NewAPI /api/farm2d) 一键偷菜执行器
-----------------------------------------------
流程 (按接口文档):
  1) 认证: 直接用 Bearer access_token, 或用 new_api_refresh cookie 走
     POST /api/user/auth/refresh 换取短期 access_token
  2) GET  /api/farm2d/farm/state      -> version, stars
  3) GET  /api/farm2d/farm/neighbors  -> 邻居及其 plots(i,c,qq,round,left,total)
  4) 收集 qq==true 的地块作为 targets
  5) POST /api/farm2d/farm/action {action: qqStealAll, params:{targets}, version}
     分批提交, 落盘结果
  6) 复取 /farm/state 与 /farm/neighbors 校验 stars 增加 / left 减少

用法:
  # 方式A: 直接给 access token
  python steal_all.py --base https://www.<HOST> --token "Bearer eyJ..."
  # 方式B: 给 refresh cookie (浏览器登录后 F12 -> Cookies -> new_api_refresh)
  python steal_all.py --base https://www.<HOST> --cookie "<new_api_refresh value>"
  # 演练 (只读, 不提交偷菜)
  python steal_all.py --base https://www.<HOST> --token "..." --dry-run
"""
import argparse, json, os, sys, time, uuid, urllib.request, urllib.error, urllib.parse, datetime

def now():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

def jwt_exp(tok):
    """返回 access_token 的 exp (epoch) 或 None"""
    try:
        t = tok.split(" ", 1)[-1]
        p = t.split(".")[1]
        p += "=" * (-len(p) % 4)
        import base64
        data = json.loads(base64.urlsafe_b64decode(p))
        return data.get("exp"), data
    except Exception:
        return None, None

class Api:
    def __init__(self, base, token=None, cookie=None, timeout=25, debug=False):
        self.base = base.rstrip("/")
        sp = urllib.parse.urlsplit(self.base)
        self.root = f"{sp.scheme}://{sp.netloc}"
        self.token = token
        self.cookie = cookie
        self.timeout = timeout
        self.debug = debug

    def _req(self, method, path, body=None, extra_headers=None):
        # path 以 /api/user 开头走站点根；其余走 /api/farm2d 基址
        if path.startswith("http"):
            url = path
        elif path.startswith("/api/user"):
            url = self.root + path
        else:
            url = self.base + path
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": self.root,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
        }
        if self.token:
            headers["Authorization"] = self.token if self.token.lower().startswith("bearer ") else "Bearer " + self.token
        if self.cookie:
            headers["Cookie"] = "new_api_refresh=" + self.cookie
        if extra_headers:
            headers.update(extra_headers)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read().decode("utf-8", "replace")
                return r.status, (json.loads(raw) if raw.strip().startswith(("{", "[")) else raw)
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, raw
        except Exception as e:
            return 0, {"error": str(e)}

    def refresh(self):
        """用 refresh cookie 换 access token"""
        st, d = self._req("POST", "/api/user/auth/refresh", {})
        if st == 200 and isinstance(d, dict) and d.get("success") and d.get("data", {}).get("access_token"):
            self.token = "Bearer " + d["data"]["access_token"]
            return True, d.get("data", {}).get("user")
        return False, d

    def state(self):
        return self._req("GET", "/farm/state")

    def neighbors(self):
        return self._req("GET", "/farm/neighbors")

    def action(self, action, params, version):
        body = {
            "action": action,
            "params": params,
            "request_id": f"farm:{action}:{uuid.uuid4()}",
            "version": version,
        }
        return self._req("POST", "/farm/action", body)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="例如 https://www.example.com/api/farm2d")
    ap.add_argument("--token", default=os.environ.get("FARM_TOKEN", ""), help="Bearer access token")
    ap.add_argument("--cookie", default=os.environ.get("FARM_REFRESH_COOKIE", ""), help="new_api_refresh cookie 值")
    ap.add_argument("--dry-run", action="store_true", help="只读, 不提交偷菜")
    ap.add_argument("--chunk", type=int, default=50, help="qqStealAll 每批 targets 数量")
    ap.add_argument("--sleep", type=float, default=0.6, help="批次之间的间隔秒")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "results"))
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    api = Api(args.base, token=args.token or None, cookie=args.cookie or None)

    # 校验 token 有效期
    if args.token:
        exp, claims = jwt_exp(args.token)
        if exp:
            delta = exp - int(time.time())
            print(f"[auth] access_token exp={datetime.datetime.utcfromtimestamp(exp)}Z  剩余 {delta}s  sub={claims.get('sub')}")
            if delta <= 0:
                print("[auth] !! access_token 已过期, 需要 --cookie 换取新 token 或提供新的 access token")

    # 若给了 cookie 先换 token
    if args.cookie:
        ok, info = api.refresh()
        print(f"[auth] refresh cookie -> {'OK user=' + str(info) if ok else 'FAILED: ' + json.dumps(info, ensure_ascii=False)}")
        if not ok:
            sys.exit(2)

    st, d = api.state()
    print(f"[state] HTTP {st}  {json.dumps(d, ensure_ascii=False)[:300]}")
    if st != 200 or not (isinstance(d, dict) and d.get("success")):
        print("[state] 认证失败/无法读取状态, 终止。请提供有效 access token 或 new_api_refresh cookie。")
        sys.exit(3)
    version = d["data"]["version"]; stars0 = d["data"]["state"]["stars"]
    print(f"[state] version={version} stars={stars0}")

    st, d = api.neighbors()
    print(f"[neighbors] HTTP {st}  success={isinstance(d, dict) and d.get('success')}")
    if st != 200 or not (isinstance(d, dict) and d.get("success")):
        print("[neighbors] 读取失败, 终止。")
        sys.exit(4)
    neighbors = d["data"]["neighbors"]
    print(f"[neighbors] 返回 {len(neighbors)} 个邻居")

    targets = []
    for n in neighbors:
        for p in n.get("plots", []):
            if p.get("qq"):
                targets.append({"victim": n["user_id"], "plot": p["i"], "round": p["round"]})
    print(f"[targets] 可偷地块 {len(targets)} 个, 来自 {len({t['victim'] for t in targets})} 个用户")
    if not targets:
        print("[targets] 无可偷地块, 结束。"); return
    if args.dry_run:
        print("[dry-run] 仅预览, 不提交:")
        print(json.dumps(targets, ensure_ascii=False, indent=2)[:2000]); return

    all_steals, all_skipped = [], []
    for i in range(0, len(targets), args.chunk):
        batch = targets[i:i + args.chunk]
        st, d = api.action("qqStealAll", {"targets": batch}, version)
        print(f"[batch {i//args.chunk+1}] HTTP {st} targets={len(batch)} -> {json.dumps(d, ensure_ascii=False)[:200]}")
        if st == 200 and isinstance(d, dict) and d.get("success"):
            r = d["data"]["result"]
            all_steals += r.get("steals", [])
            all_skipped += r.get("skipped", [])
            if "version" in d["data"]:
                version = d["data"]["version"]
        time.sleep(args.sleep)

    st2, d2 = api.state()
    stars1 = d2["data"]["state"]["stars"] if st2 == 200 and isinstance(d2, dict) and d2.get("success") else None
    summary = {
        "time": now(), "base": args.base, "version_start": version,
        "stars_start": stars0, "stars_end": stars1,
        "stolen": len(all_steals), "skipped": len(all_skipped),
        "steals": all_steals, "skipped_detail": all_skipped,
    }
    fn = os.path.join(args.out, f"steal_{now()}.json")
    with open(fn, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"[done] 成功偷取 {len(all_steals)} 个地块, 跳过 {len(all_skipped)}. stars {stars0} -> {stars1}")
    print(f"[done] 结果已保存: {fn}")

if __name__ == "__main__":
    main()
