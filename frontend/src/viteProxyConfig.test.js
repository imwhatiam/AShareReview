import { describe, expect, it } from 'vitest'

import { createDevelopmentApiProxy } from './api/developmentProxy'

describe('development API proxy', () => {
  it('forwards API requests to the configured Django backend origin', () => {
    expect(createDevelopmentApiProxy('http://127.0.0.1:8000')).toEqual({
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    })
  })
})
