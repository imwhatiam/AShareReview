---
name: local-dev-auth-diagnosis
description: 只读诊断「本地开发环境前端起来了、但 /api/ 请求全部失败」这类联调问题，尤其是登录。适用于本仓库（Vite 5173 + Django runserver）。核心方法是按 HTTP 状态码反推断点：400 裸 HTML 说明 Host 白名单拒了（没进视图）、403 CSRF_FAILED 是 CSRF 环节、401 是真到了视图的账号问题、429 是登录节流、404 MODULE_DISABLED 是模块没启用。含一个隐蔽大坑：DJANGO_ALLOWED_HOSTS 填了带端口的 `127.0.0.1:8765` 会让任何 Host 都匹配不上。当用户说"本地登录失败""登录一直说密码错误""health 返回 400""5173 打开正常但接口全挂""前端能打开但数据出不来"时使用。
version: 1.0.0
origin: custom
agent_created: true
display_name: "本地联调与登录排查"
display_name_en: "Local Dev Auth & Connectivity Diagnosis"
---

# 本地联调与登录排查

本仓库本地开发是 **Vite(`localhost:5173`) → 代理 `/api/` → Django(`runserver`)**。前端"能打开"只证明 Vite 活着，**不证明后端通**。
登录失败的第一原则：**先确认请求有没有进到 Django 视图**。没进视图的失败与密码无关，别去查账号。

## 铁律

- **只读**：不写库、不改 `.env`（除非用户明确要求修）。探针放本项目 `tests/`，用完删除。
- 探测用 `curl` 打 `/api/core/health/` 与 `/api/core/session/` —— 两者都不碰上游、不读库，零副作用。
- 要发 API 请求前先问用户有没有现成环境；有 `runserver` 在跑就直接打它，不用自己起。要起临时实例时必须换端口、`--noreload`、后台任务方式启动、不碰用户占用的端口。

## 第一步：`health` 返回什么，直接分叉

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:<port>/api/core/health/
```

- **400 + 裸 HTML（`<title>Bad Request (400)</title>`）** → **Host 白名单**，请求没进视图。跳「坑 A」。
- 200 → 后端通，问题在认证环节。跳第二步。

## 第二步：按状态码反推断点

| 观察到 | 断点在哪 | 看什么 |
|---|---|---|
| 400 裸 HTML | Host 校验（`CommonMiddleware` 之前） | `DJANGO_ALLOWED_HOSTS` |
| 403 `CSRF_FAILED` | CSRF 中间件 | 有没有带 `X-CSRFToken`、`csrftoken` cookie 在不在、`CSRF_TRUSTED_ORIGINS` 是否含前端源 |
| 401 `AUTH_REQUIRED` | **已经到视图了** | 账号密码/`is_active`；CSRF 与 Host 都是好的 |
| 429 `TOO_MANY_ATTEMPTS` | 登录节流 | `LOGIN_MAX_FAILURES`/`LOGIN_WINDOW_SECONDS`，等窗口过 |
| 404 `MODULE_DISABLED` | 路由装配 | `.env` 的 `ENABLED_MODULES` |
| 202 `DATA_PREPARING` | 读路径按需生成 | 认证已通过，是数据没算，与本技能无关 |

区分 401 与 403 是关键对照：**带 CSRF 是 401、不带是 403**，一次就能证明两层都好。

```bash
TOKEN=$(grep csrftoken tests/_cj.txt | awk '{print $7}')
curl -s -o /dev/null -w "带CSRF: %{http_code}\n" -b tests/_cj.txt \
  -H "Origin: http://localhost:5173" -H "X-CSRFToken: $TOKEN" \
  -H "Content-Type: application/json" -X POST \
  -d '{"username":"__probe_not_a_user__","password":"x"}' \
  http://127.0.0.1:<port>/api/core/login/
```

用**不存在的用户名**试，避免污染真实用户的失败预算。

## 坑 A：`DJANGO_ALLOWED_HOSTS` 不能带端口

Vite 代理是 `changeOrigin: true`（`frontend/src/api/developmentProxy.js`），会把 `Host` 改写成后端地址，如 `127.0.0.1:8765`。而 Django 校验时**先 `split_domain_port()` 剥掉端口，再拿纯域名与白名单逐字比对**：

```python
split_domain_port('127.0.0.1:8765')  # -> ('127.0.0.1', '8765')
validate_host('127.0.0.1', ['127.0.0.1:8765'])  # False！带端口的模式永远匹配不上
```

所以写 `127.0.0.1:8765` **比写生产域名还糟**：任何 Host 都过不了，包括 `example.com`。正确值：

```dotenv
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
```

两个连带结论：

- **`DJANGO_DEBUG=true` 单独改救不了**：Django 只在 `ALLOWED_HOSTS` **为空**时才在 DEBUG 下放宽为 `[".localhost","127.0.0.1","[::1]"]`；本仓库 `settings.py` 显式赋值（非空），永远不会被放宽。
- **它是启动期读取项**（`settings.py` 只在启动时读一次，只有上游凭据/超时那类才有 5 秒 TTL）→ **改完必须重启 `runserver`**，否则像是"改了没用"。

## 坑 B：前端文案会把 400 说成"密码错误"

`frontend/src/app/LoginPage.jsx` 的 `catch { setError('登录失败，请检查用户名和密码。') }` 捕获**所有**异常；400 返回 HTML，`parseEnvelope` 解析失败 → `INVALID_RESPONSE` → 也显示"请检查用户名和密码"。
**看到这句话不代表密码错了**，先 `curl` 看状态码。这也解释了为什么"密码明明是对的却登不上"。

## 一次性核对清单

```bash
grep -nE "VITE|CSRF|COOKIE|ALLOWED_HOSTS|DEBUG" .env    # 五项都要对
sqlite3 backend/data/core.sqlite3 \
  "select id,username,is_active,is_superuser from auth_user;"   # 用户在 core 库，不在 4 个业务库
```

本地开发需要同时成立的五行（README §7.2）：`DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost`、`VITE_DEV_BACKEND_ORIGIN=http://127.0.0.1:<port>`、`CSRF_TRUSTED_ORIGINS=http://localhost:5173`、`SESSION_COOKIE_SECURE=false`、`CSRF_COOKIE_SECURE=false`。

## 自证断言（避免把"配置看起来对"当成"链路通"）

必须拿到这一组对照才算修好，只看其中一条会被"改了但没重启"骗过去：

- `Host=127.0.0.1:<port>` → **200**
- `Host=localhost:5173` → **200**（Vite 代理形态）
- `Host=example.com` → **400**（确认白名单不是 `*` 在裸奔）
- 带 CSRF 的登录 POST → **401**（而非 403/400）

## 交付时的措辞

用户的 runserver 是他自己在终端起的，**改 `.env` 后要提醒他重启**，不要代他杀进程。只给命令。
