import { useEffect, useMemo, useRef } from 'react'
import { randomUUID } from '../../../utils/uuid'
import type { TaskPageContext } from './taskUiStore'
import { useTaskUiStore } from './taskUiStore'

export function useTaskPageContext(
  contexts: Array<TaskPageContext | null | undefined>,
) {
  const registerPageContext = useTaskUiStore((state) => state.registerPageContext)
  const unregisterPageContext = useTaskUiStore((state) => state.unregisterPageContext)
  const scopeIdRef = useRef(`task-page-context-${randomUUID()}`)

  const normalizedContexts = useMemo(
    () =>
      contexts.filter(
        (context): context is TaskPageContext =>
          !!context?.relationType && !!context?.relationEntityId,
      ),
    [contexts],
  )

  useEffect(() => {
    registerPageContext(scopeIdRef.current, normalizedContexts)
    return () => {
      unregisterPageContext(scopeIdRef.current)
    }
  }, [normalizedContexts, registerPageContext, unregisterPageContext])
}
