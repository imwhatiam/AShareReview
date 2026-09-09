import { useEffect, useState } from 'react'

import LoginPage from './LoginPage'

export default function AuthGate({ apiClient, authRevision, children }) {
  const [session, setSession] = useState(null)
  const [checkingSession, setCheckingSession] = useState(true)

  useEffect(() => {
    let active = true
    setCheckingSession(true)
    setSession(null)

    apiClient.request('/api/core/session/')
      .then((envelope) => {
        if (active) {
          setSession(envelope.data?.authenticated ? envelope.data : null)
        }
      })
      .catch(() => {
        if (active) {
          setSession(null)
        }
      })
      .finally(() => {
        if (active) {
          setCheckingSession(false)
        }
      })

    return () => {
      active = false
    }
  }, [apiClient, authRevision])

  async function login(credentials) {
    const envelope = await apiClient.request('/api/core/login/', {
      method: 'POST',
      body: credentials,
      notifyUnauthorized: false,
    })
    if (!envelope.data?.authenticated) {
      throw new Error('Login did not create a session.')
    }
    setSession(envelope.data)
  }

  if (checkingSession) {
    return <main role="status">正在检查登录状态…</main>
  }
  if (!session) {
    return <LoginPage onLogin={login} />
  }
  return children(session)
}
