import { useCallback, useState } from 'react'

/*
 * 一组可切换的键集合：`values.has(key)` 表示某一项是否展开/选中，`toggle(key)`
 * 增删，`replace(next)` 整体替换（例如切换业务日期后重选默认项）。
 *
 * 三个排行页此前各自手写了同一段 Set 增删；抽出来是为了让「展开/选中状态怎么变」
 * 只有一处实现，而不是为了让调用方少写三行。
 */
export default function useToggleSet() {
  const [values, setValues] = useState(() => new Set())

  const toggle = useCallback((key) => {
    setValues((previous) => {
      const next = new Set(previous)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])

  const replace = useCallback((nextValues) => {
    setValues(new Set(nextValues))
  }, [])

  return { values, toggle, replace }
}
