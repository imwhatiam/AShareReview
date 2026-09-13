import { useState } from 'react'

import Icon from '../shared/ui/Icon'

export default function LoginPage({ onLogin }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await onLogin({ username, password })
    } catch {
      setError('登录失败，请检查用户名和密码。')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="login">
      <div className="login__card">
        <div className="login__brand">
          <span className="app__brand-mark">
            <Icon name="brand" size={22} />
          </span>
          <div>
            <h1 className="login__title">登录</h1>
            <p className="login__hint">A 股市场复盘 · 板块资金流与盘后分析</p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="login__form">
          <p className="login__field">
            <label htmlFor="username">用户名</label>
            <input
              id="username"
              className="field__input"
              name="username"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              required
            />
          </p>
          <p className="login__field">
            <label htmlFor="password">密码</label>
            <input
              id="password"
              className="field__input"
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </p>
          {error && <p className="login__error" role="alert">{error}</p>}
          <button type="submit" className="btn btn--primary login__submit" disabled={submitting}>
            {submitting ? '登录中…' : '登录'}
          </button>
        </form>
      </div>
    </div>
  )
}
