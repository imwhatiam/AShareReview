export function createDevelopmentApiProxy(backendOrigin) {
  const target = backendOrigin?.trim()
  if (!target) {
    return {}
  }

  return {
    '/api': {
      target,
      changeOrigin: true,
    },
  }
}
