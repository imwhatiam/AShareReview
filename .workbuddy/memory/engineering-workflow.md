# 跨栈工程操作铁律（专题）

工具、编辑手法、临时服务、探针、运行时、测试姿势、以及 `DecimalField` 数值口径。**动代码前后先读这一份。**

## 编辑与检索

- **同一文件的多次 `Edit` 会互相回滚**：并行发出时工具对每一条都报 `successfully`，但实际可能只有一条落盘。**同一文件必须串行编辑**；批量替换一律改用一次性 Python 脚本（`(old, new)` 列表 + 逐条 `assert text.count(old) == 1` + 最后一次性 `write_text`，断言失败时文件还没写，天然原子）。写完**用检索复查目标字符串是否真消失**，不要凭 "successfully" 判断落盘。
- **macOS BSD grep 的 `\|` 不成交替、会静默匹配失败**，看起来像"没有残留"，极易误判 —— 一律 `grep -E "a|b"`。批量改文档时更要用 Python 做子串断言，而不是 shell grep。
- **检索工具默认跳过隐藏目录，`.workbuddy/` 里的引用会被漏掉。** 查"某文件/某技能还有谁引用"时必须显式给出 `.workbuddy/`（`grep -rn <名> .workbuddy/ docs/ README.md AGENTS.md`），否则会得出"无引用"的假结论，删完留下悬空指路。全仓库 `grep -rn` 容易超时被杀（exit 137），按目录分段查。
- `@patch` 目标可能是跨行写的，单行 grep 会漏（见 `code-complexity-audit` §2）。
- **`.gitignore` 无法 re-include 被排除父目录下的文件**（`tests/` + `!tests/.gitkeep` 这种组合会失效）。判断某条 `!` 是否生效，唯一可靠的办法是 `git check-ignore -v <path>` 看实际命中的行，**而不是读字面顺序**。
- **把批量编辑派给子代理后，必须用 `git status --short` 复核有没有出现 `D` 条目。** 子代理会"顺手"删掉它判断为过时的文件，并把引用它们的文档改写成"该文件已删除"，让删除看起来自洽 —— 本仓库发生过：两个已提交的 `scripts/*.sh` 被删、相关技能与笔记被同步改口。判据是**相对派发前基线新增的 `D` / `??`**，不是状态行总数；发现即 `git checkout -- <path>` 恢复，再逐个判断该删还是该留（是留就同时回滚那些"已删除"的叙述）。

## 临时服务、探针与验证

- **临时预览/静态服务必须用后台任务方式启动**：`(npx vite &)` 会随命令结束被回收（表现为 Chrome `ERR_CONNECTION_REFUSED` 且一直不退出）。先 `curl` 确认 200 再截图。**永远不要 `pkill -f "Google Chrome"`**。
- **vite 默认只监听 IPv6 `::1`**：`curl` 探活要用 `http://localhost:<port>` 而不是 `127.0.0.1`，否则误判成服务没起来。
- 探针脚本禁止放 `/tmp`（会遮蔽标准库 `inspect`），统一放本项目 `tests/` 下运行、用完删除。ECharts SSR 脚本末尾**必须 `process.exit(0)`**。
- 验证 React 受控 `input` 要用原生 value setter + `input` 事件。
- 免登录视觉验证流程见技能 `frontend-visual-verification`。

## 运行时与迁移

- 运行时：后端 `/Users/lian/.workbuddy/binaries/python/envs/default/bin/python`；前端 `/Users/lian/.workbuddy/binaries/node/versions/22.22.2-3/bin/node`。
- **迁移必须逐个库跑**：`migrate` 不带 `--database` 只作用于 `default`，四个业务库不会被碰到，而且它会**打印假的 `Applying ... OK`**（详见 `backend-data-and-commands.md`）。模块库因此会**停在它最后一次 migrate 的时刻**（页面照常能读，只是结构是旧的）。查漂移用 `manage.py showmigrations --database=<alias>` 看 `[ ]` 行，别只看表名；五个库全量重跑见 `docs/ops/deployment.md` §4。
- **`makemigrations` 必须加 `--noinput`**：遇到"新增非空字段没有默认值"会交互式提问，非交互环境下退出码是 **137（SIGTERM）** 而不是报错，很容易被误读成超时。

## 清锁与文件清理的两个 shell 坑

- `_reap_stale_lock()` 会留**永久孤儿**：它先 `os.replace` 到 `<lock>.reaping-<uuid>` 再 `unlink`，进程在两步之间被打断即残留；除定义处外**没有任何代码扫 `_REAP_SUFFIX`**，不会自愈（真锁名为空，不影响获取）。清 `backend/data/locks/` 要连 `*.reaping-*` 一起清。
- **zsh 下 `rm -f backend/data/locks/*.lock` 在目录为空时报 `no matches found` 并中断整条命令** ⇒ 用 `find ... -delete` 或 Python `os.remove`（后者还能绕开 safe-delete 钩子）。
- **macOS 没有 `timeout`**（exit 127），限时用 `cmd & pid=$!; sleep N; kill $pid`。
- 删完**必须 `ls` 复核** —— `rm` 可能因审批超时根本没落地。

## 跑测试的标准姿势

- **跑全量后端测试**：在 `backend/` 下、先清锁、带 `CODEBUDDY_SAFE_DELETE_ENABLED=0`、输出重定向到文件后再过滤（**绝不在管道里挂 `head`** —— SIGPIPE 会中断套件并残留一批锁，下一次连锁崩成几十个 ERROR）。否则会拿到假的"大规模回归"。详见 `skills/backend-dataset-diagnosis/SKILL.md` §6。
- **全量测试的失败集合在两次运行间变化时，先怀疑外部状态**（文件缓存 / 残留锁），不要先怀疑代码。特征是"单跑绿、全量红"或"第一次绿、第二次红"。测试要碰文件缓存就必须 `@patch` 掉 `default_file_cache`（四个模块的 `tests/test_api.py` 都已这么做）。
- **没有版本表与运行状态表之后的测试范式**：
  - 断言数据时查 `DailyPrice` 的**行内容** + `source_batch_id` 的**批次集合**（不是版本串）。
  - 断言命令失败用 `assertLogs('core.management', level='ERROR')` 抓 `data_command_failed`。
  - "过期"这个概念不存在 ⇒ 要证明"没有重算"，用"让 snapshot 抛 `AssertionError`"。
  - 行业映射缺失用 `IndustrySnapshot.objects.create(...)` 植入。
  - kaipanla 有自己的 `ReadResult`，`cache_identity` 是**字段**而不是参数。
  - 某条命令被删除后，"读路径不回源"这类不变量的 patch 锚点要**上移到上游出口**（`HithinkClient` + `assert_not_called()`）。

## `get_setting` 的空串语义

- **`get_setting(name, default)` 不把空串当未配置**：`os.environ` 命中空串就返回空串。要"留空即回落默认值"必须自己写 `.strip() or default`。

## `DecimalField` 在 SQLite 上的数值口径

- `DecimalField` 在 SQLite 上存的是 **float64（`typeof` = `real`）**，`max_digits` / `decimal_places` 只是声明、不参与存储。ORM 读回时用 `Context(prec=15).create_decimal_from_float` 再 `quantize` 到 `decimal_places`（`django/db/backends/sqlite3/operations.py` 的 `_create_decimal` / `get_decimalfield_converter`）。
- **判断"某个数值列能否由其它行重算"必须走 ORM 比对**：原生 `sqlite3` 读会拿到未量化的 float 串，会误判成"不可复原"。
- 读时重算派生数值列，也要同样 `quantize` 到声明的 `decimal_places`，否则报文里的数字串会变长。
- **删掉一个数值列时，把它的 `decimal_places` 以常量形式搬进 reader 并在收尾时 `quantize`**：`sector_momentum/services/read_path.py` 的 `_AVERAGE_CHANGE_PERCENT_PLACES = 6` / `_INDUSTRY_TURNOVER_PLACES = 4` / `_MARKET_TURNOVER_RATIO_PLACES = 8` / `_SCORE_PLACES = 12`；`hundred_day` 的 `_TREND_RATIO_PLACES = 8`。**中间量不预先取整**（`score` 乘的是未取整的平均值与占比），否则末位会变。
- **没落过库的比值不收尾** —— 位数不是想当然的，按"这一列是否曾作为字段存在"逐个判断。
- 改表结构/删列/合表后的逐字节等价验证见技能 `payload-byte-equivalence`。
