const DEFAULT_BACKEND_PORT = '8765'
const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1'])

/**
 * 统一解析前端应访问的后端根地址。
 *
 * 设计目的：
 * - 避免 generated client、手写 axios、图片下载地址各自解析不同的 backend origin。
 * - 本地开发时若页面运行在 `127.0.0.1`，则自动把 `localhost` 改写成 `127.0.0.1`，反之亦然。
 */
export function resolveBackendBaseUrl(): string {
  const runtimeBackendUrl = window.__ENV?.BACKEND_URL?.trim()
  const buildtimeBackendUrl = import.meta.env.VITE_BACKEND_URL?.trim()
  const buildtimeApiBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim()

  const candidates = [runtimeBackendUrl, buildtimeBackendUrl, buildtimeApiBaseUrl]

  for (const candidate of candidates) {
    const normalized = normalizeBackendCandidate(candidate)
    if (normalized) return normalized
  }

  return `${window.location.protocol}//${window.location.hostname}:${DEFAULT_BACKEND_PORT}`
}

/**
 * 基于统一的 backend origin 生成 API 根地址。
 */
export function resolveApiBaseUrl(): string {
  return `${resolveBackendBaseUrl()}/api`
}

function normalizeBackendCandidate(candidate?: string | null): string | null {
  if (!candidate) return null

  try {
    const url = new URL(candidate, window.location.origin)
    if (isLoopbackHost(url.hostname) && isLoopbackHost(window.location.hostname)) {
      url.hostname = window.location.hostname
    }
    if (!url.port) {
      url.port = DEFAULT_BACKEND_PORT
    }
    url.pathname = url.pathname.replace(/\/api\/?$/, '').replace(/\/$/, '')
    return `${url.origin}${url.pathname}`.replace(/\/$/, '')
  } catch {
    return null
  }
}

/**
 * 判断主机名是否为本地回环地址，以便开发环境保持页面与 API 使用同一种主机名。
 */
function isLoopbackHost(hostname: string): boolean {
  return LOOPBACK_HOSTS.has(hostname)
}
