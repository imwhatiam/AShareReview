import { useEffect, useMemo, useState } from 'react'

import { createApiClient } from './api/client'
import AuthGate from './app/AuthGate'
import {
  buildNavigation,
  getDefaultModuleId,
  getEnabledModules,
  getModuleComponent,
  navigationIdForModule,
} from './app/moduleRegistry'
import Icon from './shared/ui/Icon'
import TabBar from './shared/ui/TabBar'

const PRIMARY_NAV_LABEL = '一级功能模块'
const PANEL_ID = 'active-module-panel'

function AppBrand() {
  return (
    <div className="app__brand">
      <span className="app__brand-mark">
        <Icon name="brand" size={20} />
      </span>
      <div className="app__brand-text">
        <h1 className="app__brand-title">A 股市场复盘</h1>
        <p className="app__brand-subtitle">板块资金流 · 盘后结构分析</p>
      </div>
    </div>
  )
}

function AppShell({ apiClient, session }) {
  const [modules, setModules] = useState(null)
  const [selectedModuleId, setSelectedModuleId] = useState(null)
  const [loadError, setLoadError] = useState(null)

  useEffect(() => {
    let active = true
    apiClient.request('/api/core/modules/')
      .then((envelope) => {
        if (!active) return
        const enabledModules = getEnabledModules(envelope.data ?? [])
        setModules(enabledModules)
        setSelectedModuleId(getDefaultModuleId(enabledModules))
      })
      .catch(() => {
        if (active) {
          setLoadError('模块列表暂时无法加载。')
        }
      })
    return () => {
      active = false
    }
  }, [apiClient])

  if (loadError) {
    return (
      <div className="app">
        <main className="app__main" role="alert">{loadError}</main>
      </div>
    )
  }
  if (modules === null) {
    return (
      <div className="app">
        <main className="app__main" role="status">正在加载模块…</main>
      </div>
    )
  }
  if (modules.length === 0) {
    return (
      <div className="app">
        <main className="app__main" role="status">暂无已启用模块</main>
      </div>
    )
  }

  const activeModule = modules.find((module) => module.id === selectedModuleId)
    ?? modules[0]
  const navigation = buildNavigation(modules)
  const activeNavigationId = navigationIdForModule(activeModule)
  const ActiveModuleComponent = getModuleComponent(activeModule.id)
  const primaryItems = navigation
  const username = session?.user?.username

  function selectNavigation(item) {
    const currentModuleIsInItem = item.moduleIds.includes(activeModule.id)
    setSelectedModuleId(currentModuleIsInItem ? activeModule.id : item.moduleIds[0])
  }

  return (
    <div className="app">
      <header className="app__header">
        <div className="app__bar">
          <AppBrand />
          {username && (
            <div className="user-chip">
              <span className="user-chip__avatar">{username.slice(0, 1).toUpperCase()}</span>
              <span className="user-chip__name">{username}</span>
            </div>
          )}
        </div>

        <div className="app__nav">
          <TabBar
            items={primaryItems}
            activeId={activeNavigationId}
            onSelect={selectNavigation}
            label={PRIMARY_NAV_LABEL}
            panelId={PANEL_ID}
          />
        </div>
      </header>

      {/*
       * 面板的可访问名用 `aria-label` 而不是 `aria-labelledby` 指向选中的 tab：
       * 控制它的那个 tab 挂的是**导航分组**名（"板块资金流"），而面板里呈现的是
       * 具体模块（"开盘啦"）。指向 tab 会把面板的名字换成更笼统的分组名，读屏用户
       * 反而听不出自己进了哪一页。tab → 面板的关系由 tab 上的 `aria-controls`
       * 与漫游 tabindex 建立，不需要再靠名字建立一次。
       */}
      <main className="app__main" id={PANEL_ID} role="tabpanel" aria-label={activeModule.display_name}>
        {ActiveModuleComponent ? (
          <ActiveModuleComponent apiClient={apiClient} />
        ) : (
          <p className="empty-note">页面内容将在后续步骤接入。</p>
        )}
      </main>

      <footer className="app__footer">京ICP备2024096986号-1</footer>
    </div>
  )
}

export default function App({ fetchImpl }) {
  const [authRevision, setAuthRevision] = useState(0)
  const apiClient = useMemo(
    () => createApiClient({
      fetchImpl,
      onUnauthorized: () => setAuthRevision((revision) => revision + 1),
    }),
    [fetchImpl],
  )

  return (
    <AuthGate apiClient={apiClient} authRevision={authRevision}>
      {(session) => <AppShell apiClient={apiClient} session={session} />}
    </AuthGate>
  )
}
