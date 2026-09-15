# 外部数据源 Web API 文档

> 本文档介绍两个金融数据源（开盘啦、同花顺）对外提供的 Web API，涵盖每个接口获取的数据、HTTP 方法、URL、请求头、请求参数、响应示例、字段说明及 Python `requests` 调用示例。
>
> 文档中的参数值仅为示例，实际调用时请替换为真实值（如设备 ID、令牌、API Key 等凭据）。

---

## 目录

1. [数据源总览](#数据源总览)
2. [开盘啦 — 板块资金流排行](#2-开盘啦--板块资金流排行)
3. [开盘啦 — 行业股票关系快照](#3-开盘啦--行业股票关系快照)
4. [同花顺 — 个股公共市场数据与行业指数](#4-同花顺--个股公共市场数据)
5. [通用约定](#5-通用约定)
6. [已批准的数据源边界与实施约束](#6-已批准的数据源边界与实施约束)

---

## 数据源总览

| 数据源 | 用途 | 请求方式 | 接口数量 |
| --- | --- | --- | --- |
| 开盘啦 | 板块资金流排行（分页） | `POST` | 1 |
| 开盘啦 | 行业—股票关系快照 | `POST` | 2（复用同一 URL，不同 `a` 动作） |
| 同花顺 | 个股基础信息 / 行情快照 / 日线行情 | `GET` | 3 |
| 同花顺 | 行业指数清单 / 行业成分股（881xxx，仅用于补齐北交所行业归属） | `GET` | 2 |

---

## 2. 开盘啦 — 板块资金流排行

### 2.1 概述

获取板块资金流排行数据。以 `application/x-www-form-urlencoded` 表单方式发送参数，通过 `Index` 参数做分页偏移，每页最多 80 条。

- **HTTP 方法**：`POST`
- **URL**：`https://apphwshhq.longhuvip.com/w1/api/index.php`
- **Content-Type**：`application/x-www-form-urlencoded; charset=UTF-8`

### 2.2 请求头

| 请求头 | 值 |
| --- | --- |
| `Content-Type` | `application/x-www-form-urlencoded; charset=UTF-8` |
| `User-Agent` | `Dalvik/2.1.0 (Linux; U; Android 12; ALN-AL00 Build/W528JS)` |
| `Accept-Encoding` | `gzip` |
| `Connection` | `Keep-Alive` |

### 2.3 请求参数（表单字段）

| 参数名 | 类型 | 说明 | 示例值 |
| --- | --- | --- | --- |
| `Order` | int | 排序方向 | `1` |
| `a` | string | 动作名称 | `RealRankingInfo` |
| `c` | string | 控制器 | `ZhiShuRanking` |
| `st` | int | 每页条数 | `80` |
| `PhoneOSNew` | int | 平台标识 | `1` |
| `VerSion` | string | 客户端版本 | `5.23.0.4` |
| `apiv` | string | API 版本 | `w44` |
| `Type` | int | 排行类型 | `1` |
| `ZSType` | int | 指数类型。本项目板块族统一取 `4`（881xxx 行业），对应 `.env` 的 `KAIPANLA_FLOW_ZS_TYPE`；`7` 属另一指数族，本项目不使用 | `4` |
| `Index` | int | 页偏移量（`0`、`80`、`160`…） | `0` |
| `DeviceID` | string | 设备 ID | `replace-with-device-id` |
| `UserID` | string | 用户 ID（可选，非空时携带） | `""` |
| `Token` | string | 令牌（可选，非空时携带） | `""` |

### 2.4 请求示例

```
POST https://apphwshhq.longhuvip.com/w1/api/index.php
Content-Type: application/x-www-form-urlencoded; charset=UTF-8

Order=1&a=RealRankingInfo&c=ZhiShuRanking&st=80&PhoneOSNew=1&VerSion=5.23.0.4&apiv=w44&Type=1&ZSType=4&Index=0&DeviceID=replace-with-device-id
```

### 2.5 响应示例

```json
{
  "errcode": "0",
  "Time": 1734567890,
  "Day": ["2026-09-09"],
  "Count": 86,
  "list": [
    ["881129", "通信设备", 0, 2.35, 0, 1234567890, 3450000000, 3450000000, 3100000000, 1.20, 45678901234, 0, 890000000, 123456789012]
  ]
}
```

### 2.6 响应字段说明

| 字段 | 说明 |
| --- | --- |
| `errcode` | 业务返回码，`"0"` 表示成功 |
| `Time` | 数据时间戳（秒级） |
| `Day` | 业务日期数组，首元素为数据所属交易日（`YYYY-MM-DD`） |
| `Count` | 板块总数（用于计算总页数）。**实测**：当前启用的 `Type=1` / `ZSType=4`（881xxx 行业族）恒为 104，在 `st=80` 下即 2 页 —— 任何"只取一页就算完整"的假设都不成立 |
| `list` | 板块记录数组，每项为数组，按下标映射字段 |

`list` 中每一项数组的下标含义：

| 下标 | 字段 | 说明 |
| --- | --- | --- |
| `[0]` | 板块代码 | 板块唯一标识 |
| `[1]` | 板块名称 | 板块中文名称 |
| `[3]` | 涨跌幅 | 板块涨跌幅（%） |
| `[5]` | 成交额 | 板块成交金额（元） |
| `[6]` | 主力净流入 | 主力净流入（元） |
| `[7]` | 主力买入 | 主力买入额（元） |
| `[8]` | 主力卖出 | 主力卖出额（元） |
| `[9]` | 量比 | 量比 |
| `[10]` | 流通市值 | 板块流通市值（元） |
| `[12]` | 大单净流入 | 大单净流入（元） |
| `[13]` | 总市值 | 板块总市值（元） |

### 2.7 Python `requests` 调用示例

```python
import requests

url = "https://apphwshhq.longhuvip.com/w1/api/index.php"

headers = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 12; ALN-AL00 Build/W528JS)",
    "Accept-Encoding": "gzip",
    "Connection": "Keep-Alive",
}

def fetch_page(offset: int) -> dict:
    data = {
        "Order": "1",
        "a": "RealRankingInfo",
        "c": "ZhiShuRanking",
        "st": "80",
        "PhoneOSNew": "1",
        "VerSion": "5.23.0.4",
        "apiv": "w44",
        "Type": "1",
        "ZSType": "4",
        "Index": str(offset),          # 0, 80, 160, ...
        "DeviceID": "replace-with-device-id",
    }
    # 若需要鉴权，可补充：
    # data["UserID"] = "..."
    # data["Token"] = "..."

    resp = requests.post(url, data=data, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()

payload = fetch_page(0)
if str(payload.get("errcode")) == "0":
    total = int(payload.get("Count", 0))
    rows = payload.get("list", [])
    # 每项为数组：index 0=板块代码, 1=板块名称, 6=主力净流入 ...
    for item in rows:
        sector_code = item[0]
        sector_name = item[1]
        main_net_inflow = item[6]
        print(sector_code, sector_name, main_net_inflow)
```

---

## 3. 开盘啦 — 行业股票关系快照

### 3.1 概述

获取「行业—股票」关系快照，通过两级调用链构建：行业列表 → 股票列表。两个动作通过 `a` 参数区分。**本项目两级调用走同一个域名**（`apphis`，即 `.env` 的 `KAIPANLA_INDUSTRY_API_URL`）：

| 动作 | 域名 |
| --- | --- |
| 行业列表 `RealRankingInfo` | `https://apphis.longhuvip.com/w1/api/index.php` |
| 股票列表 `ZhiShuStockList_W8` | `https://apphis.longhuvip.com/w1/api/index.php` |

> 注意 `RealRankingInfo` 这个动作名在不同用途下挂在不同域名：行业快照用它取行业清单，域名是 `apphis`；板块资金流（第 2 节）也用它取名，域名却是 `apphwshhq`（`.env` 的 `KAIPANLA_API_URL`）。两者不要混用域名。

- **HTTP 方法**：`POST`
- **Content-Type**：`application/x-www-form-urlencoded; charset=UTF-8`

### 3.2 请求头

与「开盘啦板块资金流排行」相同：

| 请求头 | 值 |
| --- | --- |
| `Content-Type` | `application/x-www-form-urlencoded; charset=UTF-8` |
| `User-Agent` | `Dalvik/2.1.0 (Linux; U; Android 12; ALN-AL00 Build/W528JS)` |
| `Accept-Encoding` | `gzip` |
| `Connection` | `Keep-Alive` |

### 3.3 两个动作的请求参数

#### 3.3.1 行业列表（`RealRankingInfo`）

获取行业列表。

| 参数名 | 类型 | 说明 | 示例值 |
| --- | --- | --- | --- |
| `a` | string | 动作名称 | `RealRankingInfo` |
| `c` | string | 控制器 | `ZhiShuRanking` |
| `Order` | int | 排序方向 | `1` |
| `st` | int | 每页条数，来自 `.env` 的 `KAIPANLA_INDUSTRY_PARENT_PAGE_SIZE`（默认 `30`） | `30` |
| `Type` | int | 排行类型 | `1` |
| `ZSType` | int | 指数类型。本项目取 `4`（881xxx 行业），对应 `.env` 的 `KAIPANLA_INDUSTRY_PARENT_ZS_TYPE`；必须与 `KAIPANLA_FLOW_ZS_TYPE` 同族 | `4` |
| `Index` | int | 页偏移量 | `0` |
| `Date` | string | 业务日期 | `2026-09-10` |
| `PhoneOSNew` | int | 平台标识 | `1` |
| `DeviceID` | string | 设备 ID | `replace-with-device-id` |
| `VerSion` | string | 客户端版本 | `5.23.0.4` |
| `apiv` | string | API 版本 | `w44` |
| `UserID` / `Token` | string | 凭据（可选，非空时携带） | `""` |

#### 3.3.2 股票列表（`ZhiShuStockList_W8`）

按行业代码分页获取股票代码列表。

- **URL**：`https://apphis.longhuvip.com/w1/api/index.php`（与行业列表同一域名）

| 参数名 | 类型 | 说明 | 示例值 |
| --- | --- | --- | --- |
| `a` | string | 动作名称 | `ZhiShuStockList_W8` |
| `c` | string | 控制器 | `ZhiShuRanking` |
| `Order` | int | 排序方向 | `1` |
| `TSZB` | int | 参数 | `0` |
| `st` | int | 每页条数，来自 `.env` 的 `KAIPANLA_INDUSTRY_STOCK_PAGE_SIZE`（默认 `300`） | `300` |
| `old` | int | 参数 | `1` |
| `IsZZ` | int | 参数 | `0` |
| `Index` | int | 页偏移量 = `页号 × KAIPANLA_INDUSTRY_STOCK_PAGE_SIZE`（`0`、`300`、`600`…） | `0` |
| `Date` | string | 业务日期（**必填**，须为有效历史交易日，当日数据未入库或非交易日会返回错误） | `2026-09-09` |
| `Type` | int | 股票类型 | `6` |
| `IsKZZType` | int | 参数 | `0` |
| `PlateID` | string | 行业代码（881xxx） | `881270` |
| `PhoneOSNew` / `DeviceID` / `VerSion` / `apiv` | — | 公共参数 | 见公共参数 |
| `UserID` / `Token` | string | 凭据（可选，非空时携带） | `""` |

> 公共参数（每个动作均携带）：`PhoneOSNew`、`DeviceID`、`VerSion`、`apiv`；当 `UserID` / `Token` 非空时额外携带。

### 3.4 请求示例

```
# 行业列表
POST https://apphis.longhuvip.com/w1/api/index.php
Content-Type: application/x-www-form-urlencoded; charset=UTF-8

a=RealRankingInfo&c=ZhiShuRanking&Order=1&st=30&Type=1&ZSType=4&Index=0&Date=2026-09-10&PhoneOSNew=1&DeviceID=replace-with-device-id&VerSion=5.23.0.4&apiv=w44

# 股票列表（与行业列表同一域名）
POST https://apphis.longhuvip.com/w1/api/index.php
Content-Type: application/x-www-form-urlencoded; charset=UTF-8

a=ZhiShuStockList_W8&c=ZhiShuRanking&Order=1&TSZB=0&st=300&old=1&IsZZ=0&Index=0&Date=2026-09-09&Type=6&IsKZZType=0&PlateID=881270&PhoneOSNew=1&DeviceID=replace-with-device-id&VerSion=5.23.0.4&apiv=w44
```

### 3.5 响应示例

```json
{
  "errcode": "0",
  "list": [
    ["881129", "通信设备"],
    ["881270", "元件"]
  ]
}
```

股票列表响应中的 `list` 项为：

```json
{
  "errcode": "0",
  "list": [
    ["000801", "四川九洲"],
    ["300308", "中际旭创"]
  ]
}
```

### 3.6 响应字段说明

| 字段 | 说明 |
| --- | --- |
| `errcode` | 业务返回码，`"0"` 表示成功 |
| `list` | 行业或股票记录数组，每项为数组 |

- 行业列表（`RealRankingInfo`）中每项下标：`[0]` 行业代码，`[1]` 行业名称。
- 股票列表（`ZhiShuStockList_W8`）中每项下标：`[0]` 股票代码（6 位数字），`[1]` 股票名称。
- 两个动作的返回键都是 `list`（小写）。

### 3.7 Python `requests` 调用示例

#### 3.7.1 行业列表（`RealRankingInfo`）

```python
import requests

# 行业列表与股票列表走同一个域名（apphis）
url = "https://apphis.longhuvip.com/w1/api/index.php"

headers = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 12; ALN-AL00 Build/W528JS)",
    "Accept-Encoding": "gzip",
    "Connection": "Keep-Alive",
}

result, offset = [], 0
while True:
    data = {
        "PhoneOSNew": "1",
        "DeviceID": "replace-with-device-id",
        "VerSion": "5.23.0.4",
        "apiv": "w44",
        "a": "RealRankingInfo",
        "c": "ZhiShuRanking",
        "Order": "1",
        "st": "30",
        "Type": "1",
        "ZSType": "4",
        "Index": str(offset),
        "Date": "2026-09-10",
    }
    resp = requests.post(url, data=data, headers=headers, timeout=10)
    resp.raise_for_status()
    payload = resp.json()

    rows = payload.get("list", [])
    if not rows:
        break
    result.extend((row[0], row[1]) for row in rows)  # (行业代码, 行业名称)
    if len(rows) < 30:
        break
    offset += 30

print(result)
```

#### 3.7.2 股票列表（`ZhiShuStockList_W8`）

```python
import requests

# 与行业列表同一域名 apphis；不要用板块资金流的行情域名 apphwshhq
url = "https://apphis.longhuvip.com/w1/api/index.php"

headers = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 12; ALN-AL00 Build/W528JS)",
    "Accept-Encoding": "gzip",
    "Connection": "Keep-Alive",
}

result, offset = [], 0
while True:
    data = {
        "PhoneOSNew": "1",
        "DeviceID": "replace-with-device-id",
        "VerSion": "5.23.0.4",
        "apiv": "w44",
        "a": "ZhiShuStockList_W8",
        "c": "ZhiShuRanking",
        "Order": "1",
        "TSZB": "0",
        "st": "300",                   # KAIPANLA_INDUSTRY_STOCK_PAGE_SIZE
        "old": "1",
        "IsZZ": "0",
        "Index": str(offset),
        "Date": "2026-09-09",          # 必填，须为有效历史交易日
        "Type": "6",
        "IsKZZType": "0",
        "PlateID": "881270",          # 行业代码
    }
    resp = requests.post(url, data=data, headers=headers, timeout=10)
    resp.raise_for_status()
    payload = resp.json()

    rows = payload.get("list", [])
    if not rows:
        break
    result.extend(row[0] for row in rows)  # 6 位股票代码
    if len(rows) < 300:            # 与 st 同值
        break
    offset += 300

print(result)
```

---

## 4. 同花顺 — 个股公共市场数据

### 4.1 概述

同花顺 REST API 提供 A 股个股公共市场数据：股票基础信息、行情快照、历史日线行情。所有请求均通过 `X-api-key` 请求头鉴权。

- **Base URL**：`https://fuyao.aicubes.cn`

此外同花顺还提供同花顺行业指数（`881xxx.TI`）的清单与成分股两类接口。本项目**只用它们补齐北交所股票的行业归属**：开盘啦 881 行业族给北交所股票用的是旧代码（43/83/87），313 只 `920xxx` 无法归入任何行业，于是用同花顺 881 行业成分股**只增不删**地补上（`HITHINK_INDUSTRY_BACKFILL_ENABLED`，默认开）。行业关系的权威来源仍是开盘啦，这两类接口不改变该口径。

### 4.2 鉴权

| 请求头 | 说明 |
| --- | --- |
| `X-api-key` | API 密钥，值为服务方分配的密钥 |

### 4.3 请求一：股票基础信息列表

- **HTTP 方法**：`GET`
- **URL**：`https://fuyao.aicubes.cn/api/meta/tickers/list`

#### 请求参数

| 参数名 | 类型 | 说明 | 示例值 |
| --- | --- | --- | --- |
| `asset_type` | string | 资产类型 | `a-share` |
| `exchange` | string | 交易所（逗号分隔） | `SH,SZ,BJ` |
| `limit` | int | 每页条数（1–10000） | `1000` |
| `offset` | int | 分页偏移量 | `0` |

#### 请求示例

```
GET https://fuyao.aicubes.cn/api/meta/tickers/list?asset_type=a-share&exchange=SH%2CSZ%2CBJ&limit=1000&offset=0
X-api-key: <API_KEY>
```

#### 响应示例

```json
{
  "code": 0,
  "data": {
    "item": [
      {
        "thscode": "600000.SH",
        "ticker": "600000",
        "name": "浦发银行",
        "exchange": "SH"
      }
    ]
  }
}
```

#### 响应字段说明

| 字段路径 | 说明 |
| --- | --- |
| `code` | 业务返回码，`0` 表示成功 |
| `data.item` | 股票记录数组 |
| `data.item[].thscode` | 同花顺股票代码（含交易所后缀） |
| `data.item[].ticker` | 股票代码（6 位） |
| `data.item[].name` | 股票名称 |
| `data.item[].exchange` | 交易所（`SH` 上交所 / `SZ` 深交所 / `BJ` 北交所） |

#### Python `requests` 调用示例

```python
import requests

url = "https://fuyao.aicubes.cn/api/meta/tickers/list"
headers = {"X-api-key": "<API_KEY>"}

tickers, offset = [], 0
while True:
    params = {
        "asset_type": "a-share",
        "exchange": "SH,SZ,BJ",
        "limit": 1000,
        "offset": offset,
    }
    resp = requests.get(url, headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"业务码异常: {payload.get('code')}")

    items = (payload.get("data") or {}).get("item", [])
    if not items:
        break
    tickers.extend(items)
    if len(items) < 1000:
        break
    offset += 1000

print(tickers)
```

### 4.4 请求二：行情快照

- **HTTP 方法**：`GET`
- **URL**：`https://fuyao.aicubes.cn/api/a-share/prices/snapshot`

获取 A 股行情快照（当前时刻的全市场股票行情）。`thscodes` 显式传入（逗号分隔）时按入参顺序批量取数、不分页；**省略时遍历完整 A 股代码表（按 thscode 升序），并按 `limit` / `offset` 分页**。

#### 请求参数

| 参数名 | 类型 | 说明 | 示例值 |
| --- | --- | --- | --- |
| `thscodes` | string | 逗号分隔的 thscode 列表（可选，省略时全市场分页） | `600519.SH,000001.SZ` |
| `limit` | int | 每页条数（仅省略 `thscodes` 时生效） | `100` |
| `offset` | int | 分页偏移量（仅省略 `thscodes` 时生效） | `0` |

#### 请求示例

```
# 全市场分页（省略 thscodes）
GET https://fuyao.aicubes.cn/api/a-share/prices/snapshot?limit=100&offset=0
X-api-key: <API_KEY>

# 按 thscodes 批量取
GET https://fuyao.aicubes.cn/api/a-share/prices/snapshot?thscodes=600519.SH,000001.SZ
X-api-key: <API_KEY>
```

#### 响应示例

```json
{
  "code": 0,
  "data": {
    "timestamp": 1784275991000,
    "total": 5570,
    "item": [
      {
        "thscode": "600519.SH",
        "ticker": "600519",
        "last_price": 1277.8,
        "price_change": 21.8,
        "price_change_ratio_pct": 1.735669,
        "open_price": 1252.08,
        "high_price": 1282,
        "low_price": 1250.21,
        "prev_price": 1256,
        "volume": 3098875,
        "turnover": 3937375200
      }
    ]
  }
}
```

#### 响应字段说明

| 字段路径 | 说明 |
| --- | --- |
| `code` | 业务返回码，`0` 表示成功 |
| `data.timestamp` | 数据就绪时间（毫秒，Asia/Shanghai） |
| `data.total` | 全市场代码表总数（用于分页估算页数） |
| `data.item` | 快照记录数组 |
| `data.item[].thscode` | 带交易所后缀的完整 thscode |
| `data.item[].ticker` | 纯代码（6 位，无交易所后缀） |
| `data.item[].last_price` | 最新成交价 |
| `data.item[].price_change` | 相对前收盘价的涨跌额 |
| `data.item[].price_change_ratio_pct` | 涨跌幅（%，如 `1.74` 表示 +1.74%） |
| `data.item[].open_price` | 当日开盘价 |
| `data.item[].high_price` | 当日最高价 |
| `data.item[].low_price` | 当日最低价 |
| `data.item[].prev_price` | 前收盘价 |
| `data.item[].volume` | 成交量（股） |
| `data.item[].turnover` | 成交额（元） |

> 快照响应**不返回标的中文名**，如需展示中文名请配合 `/api/meta/tickers/list` 解析。

#### Python `requests` 调用示例

```python
import requests

url = "https://fuyao.aicubes.cn/api/a-share/prices/snapshot"
headers = {"X-api-key": "<API_KEY>"}

result, offset, limit = [], 0, 500
while True:
    params = {"limit": limit, "offset": offset}
    resp = requests.get(url, headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"业务码异常: {payload.get('code')}")

    items = (payload.get("data") or {}).get("item", [])
    if not items:
        break
    result.extend(items)
    if len(items) < limit:
        break
    offset += limit

print(result)
```

---

### 4.5 请求三：历史日线行情

- **HTTP 方法**：`GET`
- **URL**：`https://fuyao.aicubes.cn/api/a-share/prices/historical`

#### 请求参数

| 参数名 | 类型 | 说明 | 示例值 |
| --- | --- | --- | --- |
| `thscode` | string | 同花顺股票代码 | `600000.SH` |
| `interval` | string | 行情周期 | `1d` |
| `start` | int | 开始日期（毫秒时间戳，Asia/Shanghai） | `1734567890000` |
| `end` | int | 结束日期（毫秒时间戳，Asia/Shanghai） | `1767542400000` |
| `adjust` | string | 复权方式 | `forward` |
| `offset` | int | 分页偏移量 | `0` |

#### 请求示例

```
GET https://fuyao.aicubes.cn/api/a-share/prices/historical?thscode=600000.SH&interval=1d&start=1734567890000&end=1767542400000&adjust=forward&offset=0
X-api-key: <API_KEY>
```

#### 响应示例

```json
{
  "code": 0,
  "data": {
    "item": [
      {
        "date_ms": 1734567890000,
        "open_price": 10.20,
        "high_price": 10.50,
        "low_price": 10.10,
        "close_price": 10.40,
        "volume": 12345678,
        "turnover": 128765432.0
      }
    ]
  }
}
```

#### 响应字段说明

| 字段路径 | 说明 |
| --- | --- |
| `code` | 业务返回码，`0` 表示成功 |
| `data.item` | 日线记录数组 |
| `data.item[].date_ms` | 交易日毫秒时间戳（Asia/Shanghai） |
| `data.item[].open_price` | 开盘价 |
| `data.item[].high_price` | 最高价 |
| `data.item[].low_price` | 最低价 |
| `data.item[].close_price` | 收盘价 |
| `data.item[].volume` | 成交量 |
| `data.item[].turnover` | 成交额 |

#### Python `requests` 调用示例

```python
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

url = "https://fuyao.aicubes.cn/api/a-share/prices/historical"
headers = {"X-api-key": "<API_KEY>"}

SHANGHAI = ZoneInfo("Asia/Shanghai")


def to_millis(year: int, month: int, day: int) -> int:
    """将日期转为 Asia/Shanghai 当日 0 点的毫秒时间戳。"""
    dt = datetime(year, month, day, tzinfo=SHANGHAI)
    return int(dt.timestamp() * 1000)


params = {
    "thscode": "600000.SH",
    "interval": "1d",
    "start": to_millis(2025, 1, 1),
    "end": to_millis(2025, 12, 31),
    "adjust": "forward",
    "offset": 0,
}

resp = requests.get(url, headers=headers, params=params, timeout=10)
resp.raise_for_status()
payload = resp.json()
if payload.get("code") != 0:
    raise RuntimeError(f"业务码异常: {payload.get('code')}")

bars = (payload.get("data") or {}).get("item", [])
print(bars)
```

### 4.6 请求四：同花顺行业指数清单

- **HTTP 方法**：`GET`
- **URL**：`https://fuyao.aicubes.cn/api/a-share-index/catalog/ths-index-list`

按标签返回同花顺指数清单。本项目固定取 `tag=industry`（881xxx 行业），**该接口不分页，一次调用返回整个标签下的全部指数**。

#### 请求参数

| 参数名 | 类型 | 说明 | 示例值 |
| --- | --- | --- | --- |
| `tag` | string | 指数标签；`industry` = 881xxx 行业，其他标签（如概念）本项目不使用 | `industry` |

#### 请求示例

```
GET https://fuyao.aicubes.cn/api/a-share-index/catalog/ths-index-list?tag=industry
X-api-key: <API_KEY>
```

#### 响应示例

```json
{
  "code": 0,
  "data": {
    "item": [
      { "thscode": "881129.TI", "name": "通信设备" },
      { "thscode": "881270.TI", "name": "元件" }
    ]
  }
}
```

#### 响应字段说明

| 字段路径 | 说明 |
| --- | --- |
| `code` | 业务返回码，`0` 表示成功 |
| `data.item` | 指数记录数组 |
| `data.item[].thscode` | 指数代码，形如 `881129.TI`；**市场后缀必须是 `TI`**，否则不是同花顺行业板块（客户端据此校验，不匹配即判为响应非法） |
| `data.item[].name` | 行业名称 |

#### Python `requests` 调用示例

```python
import requests

url = "https://fuyao.aicubes.cn/api/a-share-index/catalog/ths-index-list"
headers = {"X-api-key": "<API_KEY>"}

resp = requests.get(url, headers=headers, params={"tag": "industry"}, timeout=10)
resp.raise_for_status()
payload = resp.json()
if payload.get("code") != 0:
    raise RuntimeError(f"业务码异常: {payload.get('code')}")

for item in (payload.get("data") or {}).get("item", []):
    industry_code, _, market = item["thscode"].partition(".")
    if market != "TI":
        continue
    print(industry_code, item["name"])   # 881129 通信设备
```

### 4.7 请求五：同花顺行业成分股

- **HTTP 方法**：`GET`
- **URL**：`https://fuyao.aicubes.cn/api/a-share-index/constituents/ths-stock-list`

返回一个同花顺行业指数当前的成分股。两个约束必须遵守：

1. **一次只能传一个 `thscode`**（上游拒绝逗号分隔的批量取数），要拿到全部行业的成分股就得逐个行业调用；
2. **接口不接受日期参数**，返回的永远是**最新**成分股，没有历史成分股可查。

#### 请求参数

| 参数名 | 类型 | 说明 | 示例值 |
| --- | --- | --- | --- |
| `thscode` | string | 行业指数代码（单个，必须带 `.TI` 后缀） | `881270.TI` |

#### 请求示例

```
GET https://fuyao.aicubes.cn/api/a-share-index/constituents/ths-stock-list?thscode=881270.TI
X-api-key: <API_KEY>
```

#### 响应示例

```json
{
  "code": 0,
  "data": {
    "item": [
      { "thscode": "000801.SZ", "ticker": "000801", "name": "四川九洲" },
      { "thscode": "300308.SZ", "ticker": "300308", "name": "中际旭创" }
    ]
  }
}
```

#### 响应字段说明

| 字段路径 | 说明 |
| --- | --- |
| `code` | 业务返回码，`0` 表示成功 |
| `data.item` | 成分股记录数组 |
| `data.item[].thscode` | 带交易所后缀的完整 thscode |
| `data.item[].ticker` | 股票代码（6 位，无后缀）——本项目只消费这个字段 |
| `data.item[].name` | 股票名称（本项目不使用，股票名以开盘啦/主数据为准） |

#### Python `requests` 调用示例

```python
import requests

url = "https://fuyao.aicubes.cn/api/a-share-index/constituents/ths-stock-list"
headers = {"X-api-key": "<API_KEY>"}

codes = []
for thscode in ["881129.TI", "881270.TI"]:      # 一次一个，逐行业调用
    resp = requests.get(url, headers=headers, params={"thscode": thscode}, timeout=10)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"业务码异常: {payload.get('code')}")
    codes.extend(
        item["ticker"]
        for item in (payload.get("data") or {}).get("item", [])
    )

print(codes)
```

### 4.8 业务返回码

同花顺 REST 的业务返回码 `code` 取值：

| `code` | 含义 |
| --- | --- |
| `0` | 成功 |
| `4001` | 频率限制（rate limit） |
| `2001` / `2003` | 认证失败 |
| `5001` / `5002` / `5003` | 服务暂不可用 |

> HTTP 状态码层面：`429` 视为频率限制，`401`/`403` 视为认证失败，其余非 2xx 视为不可用。

---

## 5. 通用约定

### 5.1 响应格式

- 开盘啦与同花顺返回标准 JSON。
- 开盘啦返回的 JSON 可能存在 Unicode 转义或控制字符，解析前可先做 `raw_unicode_escape` 解码并清理控制字符。

### 5.2 错误处理与重试

- 网络异常、非 2xx 状态、非法 JSON 均视为请求失败，建议采用有限次重试，并在请求之间加入延时以降低频率压力。
- 开盘啦按 `errcode == "0"` 判断成功；同花顺按 `code == 0` 判断成功。

### 5.3 请求频率

- 同花顺：建议逐股票低频顺序执行，避免触发 `429` 或业务码 `4001`。
- 开盘啦：单次请求之间建议留出间隔。

### 5.4 凭据安全

- 所有 API Key、Token、Device ID 等凭据应通过环境变量或配置文件注入，避免硬编码、记录或提交到版本库。
- 示例中的 `<API_KEY>`、`replace-with-device-id` 均为占位符，请替换为真实值。

---

## 6. 已批准的数据源边界与实施约束

### 已批准的数据源边界

#### 同花顺 REST：个股公共市场数据

- 鉴权：`X-api-key`，值仅从根目录 `.env` 的 `HITHINK_FINANCE_API_KEY` 读取。
- 股票列表：`GET /api/meta/tickers/list`，使用 `asset_type=a-share` 分页取得全量 A 股。
- 日线：对每个股票调用 `GET /api/a-share/prices/historical`，固定 `interval=1d` 与 `adjust=forward`，只请求最近一年。
- 行业补齐：`GET /api/a-share-index/catalog/ths-index-list` 与 `GET /api/a-share-index/constituents/ths-stock-list`，**只用于补齐北交所行业归属**。
- **交易日历不走上游**：交易日由 `chinese-calendar` 在本地推导（`core/services/calendar.py`），没有对应的上游端点，也不落库。

股票列表与单股票最近一年历史日线均返回业务 `code=0`；最近一年日线为 242 行，字段包含 `date_ms`、OHLC、`volume` 和 `turnover`。

#### 开盘啦：行业—股票关系

行业—股票快照使用历史端点 `https://apphis.longhuvip.com/w1/api/index.php`；板块资金流使用实时端点 `https://apphwshhq.longhuvip.com/w1/api/index.php`。两条链路通过独立的 `.env` 配置项 `KAIPANLA_INDUSTRY_API_URL` 与 `KAIPANLA_API_URL` 管理，不能互相替代。**行业快照的两级调用（`RealRankingInfo` → `ZhiShuStockList_W8`）都走 `apphis`**；同名动作 `RealRankingInfo` 在板块资金流里走 `apphwshhq`，不要因为动作名相同就混用域名。

`RealRankingInfo` 可获取行业列表、`ZhiShuStockList_W8` 可按行业分页获取股票列表。股票 `000801` 同时出现在多个行业的成分股中，故多行业归属是实际数据语义。

行业族固定为 **`881xxx`**：`.env` 的 `KAIPANLA_INDUSTRY_PARENT_ZS_TYPE` 与 `KAIPANLA_FLOW_ZS_TYPE` 均为 `4`，配套 `Type=1`。行业—股票快照固定保存三个业务字段：`industry_code`、`industry_name` 和 `stock_codes`（JSON 股票代码数组）。若上游存在无成分股的行业，保留该记录并保存空数组。该表不保存历史有效期。

#### 开盘啦凭据可选性

三个 `KPL_*` 值（`KPL_DEVICE_ID`、`KPL_USER_ID`、`KPL_TOKEN`）都是**可选配置**，代码仅在值非空时发送相应字段。携带三个字段与完全省略三个字段两种模式都能取得板块资金流完整分页、行业列表与股票列表。**这只是当前上游行为的实测结果，不构成稳定的匿名访问承诺。**

上游对未发布数据会返回业务码 `1020`，该失败与是否携带凭据无关。行业—股票同步应使用已发布的交易日快照，不能把盘中当日未发布数据误判为认证失败。

### 实施约束与风险

- 同花顺 REST 与开盘啦调用均采用可配置低并发、请求间隔、有限退避和超时。
- HTTP 429 或业务码 `4001`、认证/权限错误、空数据和上游超时必须保留最近成功版本，不覆盖为完整版本。
- 测试模拟上游响应，不依赖真实凭据；不得输出、记录或提交 API Key、Token 或 Device ID。
- 禁止个股爬虫、浏览器自动化、上交所/深交所旧下载和 Baostock。
- 公开文档未公布固定 QPS、并发或每日额度，连续请求可能遇到 HTTP 429。因此，逐股票最近一年初始化必须低频顺序执行，并可从失败处恢复。