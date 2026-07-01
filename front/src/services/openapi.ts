import { OpenAPI } from './generated'
import { resolveBackendBaseUrl } from './backendBase'

declare global {
  interface Window {
    __ENV?: {
      BACKEND_URL?: string
    }
  }
}

/**
 * 初始化由 OpenAPI 生成的请求客户端。
 *
 * 说明：
 * - 生成接口的路径已包含 `/api/v1/...`，因此 BASE 应为后端 origin，而不是 `/api`。
 * - 统一通过 `resolveBackendBaseUrl()` 解决 `localhost` / `127.0.0.1` 混用问题。
 */
export function initOpenAPI(base: string = '') {
  OpenAPI.BASE = base
}

initOpenAPI(resolveBackendBaseUrl())
