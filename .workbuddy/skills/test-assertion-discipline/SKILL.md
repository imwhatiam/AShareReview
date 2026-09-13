---
name: test-assertion-discipline
description: 写出"有牙"的断言，并自证断言真的有牙。适用于本仓库前后端测试（以及 shell 脚本探针）的加固与评审——识别同义反复 / 恒真 / 锁实现细节 / 读源码文本 / 只断"消失了"不断"留下的还对" / 被 .at(-1) 掩盖的跨用例泄漏这几类弱断言，用变异验证（临时改坏生产代码，确认新用例确实变红，并先确认变异体真的被跑到）证明用例不是摆设，以及修掉本仓库已踩过的具体坑（替身用非原子写导致假通过；sed 静默失败被 || true 掩盖；jsdom 下 import.meta.url 不是 file URL；模块级 vi.mock spy 不自动重置；用例游离在 describe 之外；手写契约清单会漏；交易时段断言随机器时区变色）。触发词：弱断言、测试没意义、断言加固、用例没牙、补测试、测试缺口、mock 泄漏、变异测试、mutation、变异没生效、断言锁实现细节、恒真断言、同义反复、假通过、flaky、随环境变色。
version: 1.1.0
origin: custom
agent_created: true
display_name: "测试断言加固"
display_name_en: "Test Assertion Discipline"
---

# 测试断言加固

**核心命题：一条通过了的用例，不代表它在守护任何东西。** 加固测试时，主要工作不是"多写几条"，而是把每一条断言都逼到"如果我改坏了代码，它会红"。

## 0. 一条断言算不算"有牙"：四问

对每条断言依次问，任一个答"否"就是弱断言：

1. **改坏生产代码，它会红吗？** —— 这是唯一的终极标准。答不出来就去做 §2 的变异验证，不要靠感觉。
2. **它断的是"结果"还是"实现"？** —— 断 `yAxis.length === 4`、`yAxisIndex === [1,2,3]`、`series[2].data === [12,3]` 是**实现**：合法重构（合并轴、改索引顺序）会打碎它，而真正的回归（轴错位）反而可能照样通过。要断**性质**："恰好 1 根可见轴 + 每根柱各有独立隐藏轴"。
3. **它是不是在任何代码下都真？** —— 两边同源的比较（`assertEqual(settings.SECRET_KEY, get_required_setting('SECRET_KEY'))`，而 settings.py 就是那么赋值的；"传入的 status 集合 == 枚举集合"）恒真，零覆盖，只会给出**假的安全感**。
4. **它读的是被测行为，还是源码文本？** —— `readFileSync('index.css')` 再断言含 `:focus-visible` 属于后者：jsdom 不做层叠也不做命中测试，读文本**既过严**（改个写法就挂）**又过松**（把规则写在永不匹配的选择器里照样通过）。要断样式就截图（见 `frontend-visual-verification`），要断配色就断**语义**（见 §3.3）。

## 1. 本仓库已确认的五类弱断言（含真实出处）

| 类型 | 本仓库的真实形态 |
|---|---|
| **同义反复** | `test_dataset_models.py` 曾造对象后断言"传入的 status 集合 == 枚举集合" → 已改为真存真读（`refresh_from_db`）+ 字段往返 + 排序断言 |
| **恒真式** | `test_security_settings.py` 的 `SECRET_KEY == get_required_setting(...)` 两侧同源 → 已改为断"不含 `replace-with` / `django-insecure` 前缀、长度 ≥32"，这才挡得住"照抄 `.env.example` 上线" |
| **锁实现细节** | `chartTheme.test.js` 曾断 `yAxis` 长度与 `yAxisIndex` 字面值 → 已改为从 `rankings` fixture **推导期望值**（`Number((ratio*100).toFixed(2))`），改实现不改口径就不会碎 |
| **假取消** | `client.test.js` 曾有一条名为 "preserves caller cancellation" 的用例，实际**没调用 `abort()`、没断言取消行为** → 已改为真 `AbortController` 取消，并断言它**原样抛出**（不进 `ApiClientError`，因为渲染层正是靠"不是 ApiClientError 且 `signal.aborted`"来不渲染错误态） |
| **覆盖不全却看着够** | `integration.test.jsx` 曾只覆盖 `useHundredDay` 一个 hook，且 mock 的 `request` 忽略 `signal` → 全仓**没有任何一条断言检查过 abort 是否真的发生**。已改为把四个页面按同一套不变量逐个走一遍 |
| **只断"消失了"，不断"留下的还对"** | 验 `install_intraday_cron.sh` 的标记块清理时，输入被替身意外清空，于是"旧块已清除"全绿 —— 一起断言"用户自己的条目被保留"才拦得住（见 §2.2） |

## 2. 变异验证：自证断言有牙（本技能最值得做的一步）

**做法**：临时把生产代码改坏 → 只跑相关用例 → 确认**该挂的确实挂了** → 原样还原 → 复跑确认全绿。

**判据是"挂的条数与位置要对得上"**，不是"有挂就行"：一次改动只该打挂守着那一个行为的用例。

真实例子（2026-09-13）：给四个页面新写了"切日期/离开页面必须 abort 在途请求"的用例后，把 `usePolledResource.js` 里两处 `controller.abort()` 注释掉 —— 8 条里**正好 4 条**失败（每个页面的取消用例各挂一条），行为与预期完全对应，说明断言确实钉在了 abort 上而不是碰巧通过。

```bash
# 变异 → 跑 → 还原 → 复跑，四步都要做
# 1) 改坏：if (controller) { /* TEMP-MUTATION */ }
# 2) 跑目标文件，确认失败条数与位置
# 3) 还原（用 Edit 改回原文）
# 4) 复跑确认全绿，并 grep 复查 TEMP-MUTATION 是否真的消失
grep -nE "TEMP-MUTATION|controller\.abort" src/shared/usePolledResource.js   # 用 -E，别用 \|
```

两个必须做的收尾：**还原后 grep 复查**（`Edit` 返回 "successfully" 不等于落盘正确），以及**别把变异留在工作区**。

### 2.1 变异前必须先证明"变异体真的被跑到了"

变异验证自身也会失败，而且失败得很安静。两个已真实踩过的坑：

1. **钩子没生效，变异那一跑其实跑的是原文件**。给探针加 `CRON_SCRIPT` 覆盖钩子时用了 `sed -i 's#^SCRIPT=.*#…#` —— BSD `sed` 静默没改（而我用 `|| true` 吞掉了错误码），于是"变异体"跑的仍是**真实脚本**，输出误导性的 `ALL PASS`。
   → **改文件一律用编辑工具，不用 `sed`**；并且**变异后先 `grep` 确认目标字符串真的变了**，再跑用例。判据是"跑的是变异体"而不是"我改过"。
2. **要断言"挂了几条"，而不是"挂了没有"**。变异后应看到失败条数与位置**恰好对应**被改坏的行为（例：注释掉两处 `abort()` → 正好 4 条挂，每个页面的取消用例各一条）。`ALL PASS` 与"大面积挂"都说明变异没打在预期位置。

### 2.2 替身与真实实现的语义差会造成假通过

用替身（fake binary / stub server / 内存文件）隔离外部依赖时，**替身的语义必须是真实实现的超集**，否则会出现两种相反的假象：

- 假失败：脚本是 `crontab -l | awk | crontab -` 的管道，替身却用 `cat > "$store"` 直接写同一文件 —— 写端把读端正读着的文件截断了，表现为"用户条目凭空消失"。
- **假通过（更危险）**：上例里整份文件都空了，于是"目标内容已被清除"这类断言**全部通过** —— 它测的是"文件被清空"，不是"清理逻辑正确"。

修法是让替身写**临时文件 + 原子 `mv` 替换**：读端读完才发生替换，无竞态。更一般的判据：**任何"断言某内容已消失"的用例，都必须同时断言"不该消失的内容仍在"**（本次探针里就是"用户自己的 crontab 条目被保留"）。只断"消失了"的用例，在输入变成空文件时同样会通过。

## 3. 前端专属坑（本仓库已复现）

### 3.1 `import.meta.url` 在 jsdom 下不是 file URL

```js
readFileSync(new URL('./tokens.css', import.meta.url))   // ✗ TypeError: The URL must be of scheme file
```

修法是**首行加环境指令**（该类用例只读文件、不算 DOM）：

```js
/** @vitest-environment node */
```

**不要**改成 CWD 相对路径 —— 那会把用例绑死在调用目录上（审查报告正是把"依赖 CWD"列为一类毛病）。

### 3.2 模块级 `vi.mock` spy 不自动重置，`.at(-1)` 会掩盖泄漏

`vi.mock` 的工厂会被**提升**，所以 spy 必须声明在模块级；代价是它们的调用记录**跨用例累积**（vitest 默认不清理）。而断言"取最后一次调用"（`setOption.mock.calls.at(-1)`）恰好把泄漏盖住：上一条用例留下的更晚调用会被读到，用例照样绿。

```js
describe(..., () => {
  beforeEach(() => {          // 每条用例前显式清空，让"最后一次"确实属于本条
    setOption.mockClear(); resize.mockClear(); dispose.mockClear()
  })
})
```

### 3.3 按**语义**断配色，不按字面值断

`tokens.css` 的 A 股约定是**涨红跌绿**（与欧美相反）。写反不会让任何组件报错、不会让任何布局错位，只会让全站红绿含义整体反向 —— 这是最容易发生也最难被其它用例发现的回归。所以断**色相**而不是断十六进制值（断值只是把令牌抄一遍，两边一起改照样通过）：

```js
expect(hue(up) >= 330 || hue(up) <= 20).toBe(true)   // 红在色环两端
expect(hue(down)).toBeGreaterThan(90)
expect(hue(down)).toBeLessThan(170)                  // 绿在中间偏青
expect(token('--color-error')).not.toBe(token('--color-market-up'))
```

### 3.4 交易时段判定必须锚定 `Asia/Shanghai`

用浏览器本地时区判时段，非 UTC+8 的机器会把轮询窗口整体平移（UTC 机器的 01:30 被判成交易时段）。测试也同样会**随运行机器时区变色** —— 用 `Intl.DateTimeFormat` + `timeZone: 'Asia/Shanghai'` + **`hourCycle: 'h23'`**（不是 `hour12: false`，后者可能出现 `"24"`），并在测试里用带 `+08:00` 的 ISO 串构造时间，另加两条 UTC 视角的用例把跨时区行为钉住。

### 3.5 组织性错误也算缺口

用例**游离在 `describe` 之外**仍会执行，所以不会报错、不会失败，只是没人能在报告里认出它属于哪一组。用 `grep -nE "^describe|^\}\)|^  it\("` 扫一遍结构，确认每条 `it` 都在 `describe` 内、且每个 `describe` 都闭合。

## 4. 后端专属坑

### 4.1 手写的契约清单一定会漏

`test_management_contract.py` 曾用一张硬编码的命令→参数映射表，于是新增命令（`refresh_intraday_quotes`）时清单不会报错，只是**少覆盖一个**。改为从命令自己的定义**推导**：

```python
from django.core.management import get_commands, load_command_class

def _discover_data_commands() -> set[str]:
    return {name for name, app_label in get_commands().items()
            if isinstance(load_command_class(app_label, name), BaseDataCommand)}

def _required_arguments(command_name):
    command = load_command_class(get_commands()[command_name], command_name)
    for action in command.create_parser('manage.py', command_name)._actions:  # noqa: SLF001
        if action.required:
            return action.option_strings[0], ...
```

要点：用 `action.required` **推导**必填参数，而不是抄一份"哪些命令要 `--date`"的清单 —— 后者正是这条用例原本的病。

### 4.2 判回归的口径（细节见 `backend-dataset-diagnosis` §6）

清 `backend/data/locks/*.lock` 与 `backend/cache/` → 带 `CODEBUDDY_SAFE_DELETE_ENABLED=0` → 输出**重定向到文件后再过滤**（绝不在管道里挂 `head`，SIGPIPE 会把套件中断并留下一批锁）→ 只认这一次干净运行的结果。

**并且要注意："既有失败"是会消失的。** 本仓库曾长期记录 `test_runtime_security_settings_are_safe_by_default` 为"环境耦合的既有失败"，后来它改成了在调试口径 `.env` 下 `skipTest` —— 于是那个 `skipped=1` 就是它，**全量变成了真绿**。旧笔记里"从失败集合扣掉这一条"的说法随之作废，照旧笔记执行会把一次真实回归算成"已知问题"。

## 5. 加固时的判断顺序

1. 先看清楚**被测的是什么行为**，一句话写下来（写不出来说明这条用例本来就不知道该守什么）。
2. 问 §0 的四问，定位它属于哪一类弱断言。
3. 改断言：断结果、断性质、断语义；能从 fixture 推导的就推导，别写字面值。
4. 补齐**缺口**（尤其是"全仓没有任何一条断言检查过 X"这种）—— 这类缺口比弱断言更危险，因为它连假的安全感都不给。
5. 做 §2 的变异验证自证有牙。
6. 跑全量 + lint（前端 `eslint src`），确认没把别的东西弄坏。
