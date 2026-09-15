---
name: payload-byte-equivalence
description: 证明一次表结构重构（合并表 / 删列 / 换外键）没有改变对外 API 报文。适用于"把派生字段从库里删掉、改成读时现算"这类改动的验收——用 MigrationExecutor 在迁移前导出旧表原始行当事实底本，迁移后拿新读路径的报文逐字段比对；以及判定"能不能拿 git HEAD 当改动前"（有未提交的多轮改动时不能）、给比对脚本加非空性护栏、迁移后核对行数/回填 NULL、以及真重跑一次确认端到端仍然一致。触发词：报文不变、逐字节一致、payload 不变、表结构重构、合并表、删列、迁移验证、schema 重构、读时现算、派生字段不落库、旧表底本、MigrationExecutor、非空性护栏、vacuously passing、迁移后核对。
version: 1.1.0
origin: custom
agent_created: true
display_name: "报文逐字节不变验证"
display_name_en: "Payload Byte-Equivalence Proof"
---

# 报文逐字节不变验证

**核心命题：当改动是"把存过的数字改成读时现算"，唯一有说服力的验收是"对外报文逐字段没变"。**
而"没变"不能用"我读了一遍新代码觉得一样"来证明 —— 必须拿一份**独立于新代码**的底本去比。

## 0. 先判一件事：能不能拿 `git HEAD` 当"改动前"

**多数情况下不能。** 本仓库的工作树常年带着好几轮未提交的改动（模块改名、删服务、删表……），
`git diff --stat HEAD` 会把它们全算进来。拿 HEAD 当基线，比对结果里混着无关差异，你会花时间
逐个解释噪声，还可能把一个真差异当成噪声放过去。

判据：`git diff --stat HEAD -- <本次改动涉及的文件>` 的**改动规模远大于本次改动**时，HEAD 不可用。
（注意：diff 里常混入改名等无关项，判读前先剔除。）

**能用的替代：不比代码，比数据。** 报文是"表里的行"的确定性函数，所以只要拿到**迁移前**的原始行，
就能构造出期望值，完全不依赖旧代码。

## 1. 事实底本：迁移前把旧表导成 JSON

旧模型已经不在工作树里了，但**迁移图里还留着它们的定义**。用 `MigrationExecutor` 加载迁移前的
项目状态即可读出旧表原始行：

```python
from django.db import connections
from django.db.migrations.executor import MigrationExecutor

PRE_MIGRATION_STATE = {
    # 每个模块：迁移前的最后一个节点 + 那一刻存在的模型
    'stock_moves': ('0007_drop_run_table_and_source_versions',
                    ['StockMoveResult', 'StockMoveItem']),
    'sector_momentum': ('0002_drop_run_table_and_source_versions',
                        ['SectorMomentumResult', 'SectorMomentumRanking']),
    'hundred_day': ('0005_drop_industry_stock_detail_json',
                    ['HundredDayResult', 'HundredDayTrend',
                     'HundredDayStockFlag', 'HundredDayIndustrySummary']),
}

connection = connections[alias]
state = MigrationExecutor(connection).loader.project_state([(alias, leaf)])
model = state.apps.get_model(alias, model_name)          # 历史模型
rows = [dict(row) for row in model.objects.using(alias).all().values()]
```

要点：

- **节点名要写"迁移前的最后一个"**，即本次新迁移的父节点。先 `ls <app>/migrations/*.py` 确认。
- 用 `.values()` 走 ORM，**不要用原生 `sqlite3`**：`DecimalField` 在 SQLite 上是 float64，ORM 读回
  会 `quantize` 到声明的 `decimal_places`，原生读拿到的是未量化串 —— 会制造一堆假不符。
- 存盘用 `cls=DjangoJSONEncoder`（与响应体同一个编码器），Decimal / date / datetime 的渲染就与报文一致。
- **这一步必须在 `migrate` 之前跑**，旧表一删就再也造不出来。产物（如 `tests/_legacy_rows.json`）是
  不可再生的审计底本。
- **但本项目要求 `tests/` 用完即清**，底本与探针脚本都不会长期留在盘上。所以别把它当长期审计底本 —— 正确做法是：**当场把比对结论（比对项数、差异 0）写进 `.workbuddy/memory/` 的相关主题文件**，底本只用于当次核对。

两个脚本的写法（本次已被清理，需要时按下面的要点重建）：
`tests/_capture_legacy_rows.py`（迁移前导出旧表原始行）、`tests/_verify_payload_equivalence.py`（比对）。

## 2. 期望值从哪来：优先"旧表存过的"

**先问：这个字段旧表存过吗？** 存过就直接读，这是最硬的证据 —— 期望值来自旧数据、与被测代码无关。

多数情况下旧表把报文里几乎每个数字都直接存过（各种计数、去重数、名次、日级标量、比值……），
所以绝大部分比对项都能这么拿到。

**只有旧表从没存过的字段才需要"独立规则"**，而且要挑不依赖被测代码的规则：

| 报文里的东西 | 旧表里有没有 | 怎么得到期望值 |
| --- | --- | --- |
| 各分组计数、去重股票数、日级标量 | 有 | 直接读 |
| 名次 `rank` | 有（旧列） | 直接读，**不要**按新排序规则重算（那是循环论证） |
| 趋势点比值 | 有（`decimal_places=8`） | 直接读（ORM 已量化） |
| 行业明细名单 | **没有**（本来就是现算的） | 独立规则：长度 == 计数；每个元素都在该行业 `industries` 里且确实带对应旗标 |
| 当日比值 | **没有**（从未落库） | `str(Decimal(count) / Decimal(total))`，**不取整** |
| 顺序类（`stock_codes`） | 没有 | 按页面分组顺序 + 组内排名重排，与前端消费顺序对齐 |

**别把"新代码怎么算的"抄进期望值。** 那叫同义反复。拿不准就去读前端消费方，看它实际依赖什么顺序/精度。

本次的比对脚本 `tests/_verify_payload_equivalence.py`（1264 项比对全一致）已随 `tests/` 清理一并删除，需要时按本节规则重建。

## 3. 非空性护栏（否则"什么都没比"也算通过）

比对脚本只在**不符**时打印，所以"选择器写错、一条都没比上"会安静地报 OK。
必须加一个下限：

```python
CHECKS = 0
def check(label, expected, actual):
    global CHECKS
    CHECKS += 1
    if normalise(expected) != normalise(actual):
        FAILURES.append(label); ...
# 结尾
print(f'比对项：{CHECKS}')
if CHECKS < 20:                       # 下限按数据量给，宁可高
    print('FAILED: 比对项太少 —— 数据或选择器不对，结果不可信'); sys.exit(1)
```

同时把 `check` 的计数打进输出，**在结论里报出这个数字**（"1264 项全部一致"比"全部一致"强得多）。

## 4. 迁移前后的动作清单

1. **备份**：`cp -p` 每个受影响的模块库到 `backend/data/_backup_before_<改动名>_<日期>/`。
2. **跑第 1 步的捕获脚本**（必须在 migrate 之前）。
3. **逐库迁移**：`migrate <app> --database=<alias> --noinput`。
   **裸 `migrate` 只动 `default`**，业务模块库一个都不会被碰到（漏掉会停在旧结构上）。
4. **核对行数、逐日分布、回填 NULL**：
   ```bash
   sqlite3 backend/data/<module>.sqlite3 \
     "select business_date, count(*) from <table> group by business_date order by business_date"
   sqlite3 backend/data/<module>.sqlite3 "select count(*) from <table> where business_date is null"
   ```
   期望：总数与迁移前一致、**NULL 回填为 0**。
5. **跑第 2 步的比对脚本**。
6. **手写迁移时**：回填里带**校验**。例：`hundred_day` 的回填要求"业务日期那个趋势点的三个数
   必须等于旧结果行"，不等就 `RuntimeError` 让运维重跑构建命令 —— 迁移可以失败，但不能静默地把
   一份对不上的数据搬过去。

## 5. 补最后一刀：真重跑一次

比对通过只证明"迁移搬得对"。如果这次改动还改了**写入路径**（例如把写入从 `update_or_create` 改成
"先删后写"、新增了 `published_at` 这类字段），必须再跑一次真命令，然后确认三件事：

```bash
# 重跑前
sqlite3 backend/data/stock_moves.sqlite3 \
  "select business_date, count(*), max(published_at) from stock_moves_stockmoveitem group by business_date"
python manage.py build_stock_moves --date <已存在的某一天>
# 重跑后：行数不变、published_at 前进、再跑一遍比对脚本仍然一致
```

这一步是**唯一**能证明"重跑是幂等的、且缓存身份会前进"的方法。已实测：重跑让 `published_at` 从
`07:35:02` 走到次日 `06:03:32`，行数仍是 46、报文逐字段不变。

## 6. 别忘了信封

`data` 之外还有外壳：`data_updated_at` 这类"数据时刻"字段若也换了来源（`created_at` → `published_at`），
要单独核对一遍**迁移是否把它原样搬过来了**：

```python
# 旧表 created_at  vs  迁移后 published_at —— 应逐行相等（除了你主动重跑的那一天）
```

## 7. 坑

- **BSD `grep` 的 `\|` 不成交替、静默匹配失败**：用 `grep -E "a|b"`。验证"改动是否落盘"时踩这个坑
  会把"已落盘"误报成"没落盘"（本仓库已两次踩到）。
- **`makemigrations <app>` 卡住 → 退出码 137（SIGTERM）**：是交互式提问（"非空字段没有默认值"）。
  加 `--noinput` 才能看到真实报错。
- **索引名超 30 字符会触发无意义的 rename 迁移**：在 `Meta.indexes` 里显式给短 `name=`。
- **约束名必须与模型逐字对齐**：改完跑 `makemigrations --check --dry-run`，必须报 `No changes detected`。
- **别让 Django 自动生成迁移**：自动版对"删列 + 改键"会 drop 旧表丢数据。手写迁移能加可空列 →
  `RunPython` 回填 → 收紧为非空 → 建索引/约束 → 删旧列/旧表，全程不丢一行、**不需要重跑任何构建命令**。
- **前缀 `_` 的脚本不会被 `manage.py test` 收集**，所以审计脚本放 `tests/_*.py` 是安全的。
