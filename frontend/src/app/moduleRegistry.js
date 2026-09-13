import KaipanlaPage from '../features/kaipanla/KaipanlaPage'
import StockMovesPage from '../features/stock-moves/StockMovesPage'
import HundredDayPage from '../features/hundred-day/HundredDayPage'
import SectorMomentumPage from '../features/sector-momentum/SectorMomentumPage'

const FUND_FLOW_GROUP = 'fund_flow'

export function getEnabledModules(modules) {
  return [...modules]
    .filter((module) => module.enabled !== false)
    .sort((left, right) => left.navigation_order - right.navigation_order)
}

export function getDefaultModuleId(modules) {
  return modules.find((module) => module.id === 'kaipanla')?.id ?? modules[0]?.id ?? null
}

export function buildNavigation(modules) {
  const fundFlowModules = modules.filter(
    (module) => module.navigation_group === FUND_FLOW_GROUP,
  )
  const analysisModules = modules.filter(
    (module) => module.navigation_group !== FUND_FLOW_GROUP,
  )
  // 一级 Tab 只用文字标签，不带图标（四个 Tab 的左侧图标已按需求去掉）。
  const navigation = analysisModules.map((module) => ({
    id: module.id,
    label: module.display_name,
    moduleIds: [module.id],
  }))

  if (fundFlowModules.length > 0) {
    navigation.unshift({
      id: FUND_FLOW_GROUP,
      label: '板块资金流',
      moduleIds: fundFlowModules.map((module) => module.id),
    })
  }

  return navigation
}

export function navigationIdForModule(module) {
  return module.navigation_group === FUND_FLOW_GROUP
    ? FUND_FLOW_GROUP
    : module.id
}

export function getModuleComponent(moduleId) {
  if (moduleId === 'kaipanla') return KaipanlaPage
  if (moduleId === 'stock_moves') return StockMovesPage
  if (moduleId === 'sector_momentum') return SectorMomentumPage
  if (moduleId === 'hundred_day') return HundredDayPage
  return null
}
