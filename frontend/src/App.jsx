import { useEffect, useMemo, useRef, useState } from 'react'

import { createApiClient } from './api/client'
import AuthGate from './app/AuthGate'
import {
  buildNavigation,
  getDefaultModuleId,
  getEnabledModules,
  getModuleComponent,
  navigationIdForModule,
} from './app/moduleRegistry'

function AppShell({ apiClient }) {
  const [modules, setModules] = useState(null)
  const [selectedModuleId, setSelectedModuleId] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const primaryTabRefs = useRef(new Map())
  const fundFlowTabRefs = useRef(new Map())

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
    return <main role="alert">{loadError}</main>
  }
  if (modules === null) {
    return <main role="status">正在加载模块…</main>
  }
  if (modules.length === 0) {
    return <main role="status">暂无已启用模块</main>
  }

  const activeModule = modules.find((module) => module.id === selectedModuleId)
    ?? modules[0]
  const navigation = buildNavigation(modules)
  const activeNavigationId = navigationIdForModule(activeModule)
  const ActiveModuleComponent = getModuleComponent(activeModule.id)
  const fundFlowModules = modules.filter(
    (module) => module.navigation_group === 'fund_flow',
  )

  function selectNavigation(item) {
    const currentModuleIsInItem = item.moduleIds.includes(activeModule.id)
    setSelectedModuleId(currentModuleIsInItem ? activeModule.id : item.moduleIds[0])
  }

  function moveTab(event, items, currentIndex, onSelect, refs) {
    const keys = { ArrowRight: 1, ArrowLeft: -1 }
    let nextIndex
    if (event.key === 'Home') nextIndex = 0
    else if (event.key === 'End') nextIndex = items.length - 1
    else if (keys[event.key]) {
      nextIndex = (currentIndex + keys[event.key] + items.length) % items.length
    } else {
      return
    }
    event.preventDefault()
    const nextItem = items[nextIndex]
    onSelect(nextItem)
    requestAnimationFrame(() => refs.current.get(nextItem.id)?.focus())
  }

  return (
    <>
      <header>
        <h1>A 股市场复盘</h1>
        <nav aria-label="功能模块">
          <div role="tablist" aria-label="一级功能模块">
            {navigation.map((item) => (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={activeNavigationId === item.id}
                aria-controls="active-module-panel"
                tabIndex={activeNavigationId === item.id ? 0 : -1}
                ref={(element) => {
                  if (element) primaryTabRefs.current.set(item.id, element)
                  else primaryTabRefs.current.delete(item.id)
                }}
                onClick={() => selectNavigation(item)}
                onKeyDown={(event) => moveTab(
                  event, navigation, navigation.indexOf(item), selectNavigation, primaryTabRefs,
                )}
              >
                {item.label}
              </button>
            ))}
          </div>
        </nav>
        {activeNavigationId === 'fund_flow' && (
          <nav aria-label="板块资金流子模块">
            <div role="tablist" aria-label="板块资金流子模块">
              {fundFlowModules.map((module) => (
                <button
                  key={module.id}
                  type="button"
                  role="tab"
                  aria-selected={activeModule.id === module.id}
                  aria-controls="active-module-panel"
                  tabIndex={activeModule.id === module.id ? 0 : -1}
                  ref={(element) => {
                    if (element) fundFlowTabRefs.current.set(module.id, element)
                    else fundFlowTabRefs.current.delete(module.id)
                  }}
                  onClick={() => setSelectedModuleId(module.id)}
                  onKeyDown={(event) => moveTab(
                    event, fundFlowModules, fundFlowModules.indexOf(module),
                    (item) => setSelectedModuleId(item.id), fundFlowTabRefs,
                  )}
                >
                  {module.display_name}
                </button>
              ))}
            </div>
          </nav>
        )}
      </header>
      <main id="active-module-panel" role="tabpanel" aria-label={activeModule.display_name}>
        <p>当前模块：{activeModule.display_name}</p>
        {ActiveModuleComponent ? (
          <ActiveModuleComponent apiClient={apiClient} />
        ) : (
          <p>页面内容将在后续步骤接入。</p>
        )}
      </main>
    </>
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
      {() => <AppShell apiClient={apiClient} />}
    </AuthGate>
  )
}
