import { useEffect, useMemo, useState } from 'react'
import { Button, Card, Empty, Input, Modal, Space, Tag, message, Pagination } from 'antd'
import { DeleteOutlined, EditOutlined, LinkOutlined, PlusOutlined } from '@ant-design/icons'
import { useParams, useNavigate } from 'react-router-dom'
import { StudioShotLinksService } from '../../../../../services/generated'
import type { ProjectSceneLinkRead } from '../../../../../services/generated'
import { buildFileDownloadUrl, resolveAssetUrl } from '../../../assets/utils'
import { DisplayImageCard } from '../../../assets/components/DisplayImageCard'
import { StudioEntitiesApi } from '../../../../../services/studioEntities'
import { StudioAssetTypeFormModal } from '../../../assets/components/StudioAssetTypeFormModal'
import { encodeWorkbenchAssetEditReturnTo } from '../utils/workbenchAssetReturnTo'

type SceneLike = {
  id: string
  name: string
  description?: string | null
  thumbnail?: string
}

function getApiErrorDetail(error: unknown, fallback: string): string {
  if (error && typeof error === 'object' && 'body' in error) {
    const body = (error as { body?: { detail?: string; message?: string } }).body
    if (typeof body?.detail === 'string' && body.detail.trim()) return body.detail
    if (typeof body?.message === 'string' && body.message.trim()) return body.message
  }
  if (error instanceof Error && error.message.trim()) return error.message
  return fallback
}

export function ScenesTab() {
  const navigate = useNavigate()
  const { projectId } = useParams<{ projectId: string }>()

  const [links, setLinks] = useState<ProjectSceneLinkRead[]>([])
  const [linksLoading, setLinksLoading] = useState(false)
  const [scenesById, setScenesById] = useState<Record<string, SceneLike>>({})

  const [createModalOpen, setCreateModalOpen] = useState(false)
  const [linkModalOpen, setLinkModalOpen] = useState(false)
  const [scenes, setScenes] = useState<SceneLike[]>([])
  const [scenesLoading, setScenesLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [linkingId, setLinkingId] = useState<string | null>(null)
  const [unlinkingId, setUnlinkingId] = useState<number | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(12)

  // 按 scene_id 去重：每个场景只展示一张卡，记录该场景的所有 link id（用于批量取消关联）
  const uniqueLinks = useMemo(() => {
    const seen = new Map<string, ProjectSceneLinkRead & { allLinkIds: number[] }>()
    for (const l of links) {
      if (seen.has(l.scene_id)) {
        seen.get(l.scene_id)!.allLinkIds.push(l.id)
      } else {
        seen.set(l.scene_id, { ...l, allLinkIds: [l.id] })
      }
    }
    return Array.from(seen.values())
  }, [links])

  const sceneLinkById = useMemo(() => {
    const map = new Map<string, ProjectSceneLinkRead & { allLinkIds: number[] }>()
    uniqueLinks.forEach((link) => map.set(link.scene_id, link))
    return map
  }, [uniqueLinks])

  const linkedSceneIdSet = useMemo(() => new Set(links.map((l) => l.scene_id)), [links])

  const visibleScenes = useMemo(() => {
    const linkedScenes = uniqueLinks
      .map((link) => scenes.find((scene) => scene.id === link.scene_id) ?? scenesById[link.scene_id])
      .filter(Boolean) as SceneLike[]
    const unlinkedScenes = scenes.filter((scene) => !linkedSceneIdSet.has(scene.id))
    return [...linkedScenes, ...unlinkedScenes]
  }, [linkedSceneIdSet, scenes, scenesById, uniqueLinks])

  const pagedScenes = useMemo(() => {
    const start = (page - 1) * pageSize
    return visibleScenes.slice(start, start + pageSize)
  }, [page, pageSize, visibleScenes])

  useEffect(() => {
    setPage(1)
  }, [visibleScenes.length])

  const loadLinks = async () => {
    if (!projectId) return
    setLinksLoading(true)
    try {
      const res = await StudioShotLinksService.listProjectEntityLinksApiV1StudioShotLinksEntityTypeGet({
        entityType: 'scene',
        projectId,
        chapterId: null,
        shotId: null,
        assetId: null,
        order: null,
        isDesc: false,
        page: 1,
        pageSize: 100,
      })
      const items = (res.data?.items ?? []) as ProjectSceneLinkRead[]
      setLinks(items)

      const ids = Array.from(new Set(items.map((l) => l.scene_id)))
      const fetched = await Promise.all(
        ids.map((id) =>
          StudioEntitiesApi.get('scene', id)
            .then((r) => (r.data ?? null) as SceneLike | null)
            .catch(() => null),
        ),
      )
      const next: Record<string, SceneLike> = {}
      fetched.filter(Boolean).forEach((s) => {
        next[(s as SceneLike).id] = s as SceneLike
      })
      setScenesById(next)
    } catch {
      message.error('加载项目场景关联失败')
      setLinks([])
      setScenesById({})
    } finally {
      setLinksLoading(false)
    }
  }

  const loadScenes = async (searchQuery?: string) => {
    setScenesLoading(true)
    try {
      const q = (searchQuery !== undefined ? searchQuery : search).trim()
      const res = await StudioEntitiesApi.list('scene', {
        q: q ? q : null,
        order: 'updated_at',
        isDesc: true,
        page: 1,
        pageSize: 100,
      })
      setScenes((res.data?.items ?? []) as SceneLike[])
    } catch {
      message.error('加载场景失败')
      setScenes([])
    } finally {
      setScenesLoading(false)
    }
  }

  useEffect(() => {
    void loadLinks()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  useEffect(() => {
    void loadScenes('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  useEffect(() => {
    if (linkModalOpen) void loadScenes('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linkModalOpen])

  const availableScenes = useMemo(() => scenes.filter((s) => !linkedSceneIdSet.has(s.id)), [scenes, linkedSceneIdSet])

  const toThumbUrl = (thumbnail?: string) => {
    const url = resolveAssetUrl(thumbnail)
    if (url) return url
    // 兼容后端返回 file_id 的情况
    if (thumbnail && !thumbnail.includes('/') && !thumbnail.includes(':')) return buildFileDownloadUrl(thumbnail)
    return undefined
  }

  const handleLinkScene = async (scene: SceneLike) => {
    if (!projectId) return
    setLinkingId(scene.id)
    try {
      await StudioShotLinksService.createProjectSceneLinkApiV1StudioShotLinksScenePost({
        requestBody: { project_id: projectId, chapter_id: null, shot_id: null, asset_id: scene.id },
      })
      message.success(`已关联场景「${scene.name}」到项目`)
      setLinkModalOpen(false)
      await loadLinks()
    } catch {
      message.error('关联失败')
    } finally {
      setLinkingId(null)
    }
  }

  const handleUnlinkScene = async (link: ProjectSceneLinkRead & { allLinkIds: number[] }) => {
    setUnlinkingId(link.id)
    try {
      // 删除该场景在本项目的所有关联记录（含镜头级关联）
      await Promise.all(
        link.allLinkIds.map((id) =>
          StudioShotLinksService.deleteProjectSceneLinkApiV1StudioShotLinksSceneLinkIdDelete({ linkId: id }),
        ),
      )
      message.success('已取消关联')
      await loadLinks()
    } catch {
      message.error('取消关联失败')
    } finally {
      setUnlinkingId(null)
    }
  }

  const handleDeleteScene = async (scene: SceneLike) => {
    setDeletingId(scene.id)
    try {
      await StudioEntitiesApi.remove('scene', scene.id)
      message.success(`已删除场景「${scene.name}」`)
      await Promise.all([loadLinks(), loadScenes('')])
    } catch (error) {
      message.error(getApiErrorDetail(error, '删除失败'))
    } finally {
      setDeletingId(null)
    }
  }

  if (!projectId) return null

  return (
    <div className="h-full overflow-auto">
      <Card
        title="项目场景"
        extra={
          <Space>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModalOpen(true)}>
              新建
            </Button>
            <Button
              type="primary"
              icon={<LinkOutlined />}
              onClick={() => {
                setSearch('')
                setLinkModalOpen(true)
              }}
            >
              从资产库关联
            </Button>
            <Button icon={<PlusOutlined />} onClick={() => navigate('/assets?tab=scene')}>
              前往资产管理
            </Button>
          </Space>
        }
      >
        {visibleScenes.length === 0 && !linksLoading && !scenesLoading ? (
          <Empty description="暂无场景资产，可先新建或从资产库补充" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {pagedScenes.map((scene) => {
              const link = sceneLinkById.get(scene.id)
              const isLinked = Boolean(link)
              return (
                <DisplayImageCard
                  key={scene.id}
                  title={
                    <div className="flex items-center gap-2 min-w-0">
                      <div className="truncate">{scene.name}</div>
                      <Tag color={isLinked ? 'green' : 'default'} className="shrink-0">
                        {isLinked ? '已关联' : '未关联'}
                      </Tag>
                    </div>
                  }
                  imageUrl={toThumbUrl(link?.thumbnail ?? scene.thumbnail)}
                  imageAlt={scene.name}
                  extra={
                    <Space size="small">
                      <Button
                        type="default"
                        size="small"
                        icon={<EditOutlined />}
                        onClick={() =>
                          navigate(
                            `/assets/scenes/${scene.id}/edit?returnTo=${encodeWorkbenchAssetEditReturnTo(projectId, 'scenes')}`,
                          )
                        }
                      >
                        编辑
                      </Button>
                      {isLinked && link ? (
                        <Button
                          size="small"
                          danger
                          loading={unlinkingId === link.id}
                          onClick={() => {
                            Modal.confirm({
                              title: `从当前项目移除「${scene.name}」？`,
                              content:
                                link.allLinkIds.length > 1
                                  ? `该场景在本项目中有 ${link.allLinkIds.length} 条关联记录（含镜头级关联），将全部删除。`
                                  : undefined,
                              okText: '从项目移除',
                              cancelText: '取消',
                              okButtonProps: { danger: true },
                              onOk: () => handleUnlinkScene(link),
                            })
                          }}
                        >
                          从项目移除
                        </Button>
                      ) : (
                        <Button type="primary" size="small" loading={linkingId === scene.id} onClick={() => handleLinkScene(scene)}>
                          关联到项目
                        </Button>
                      )}
                      <Button
                        size="small"
                        icon={<DeleteOutlined />}
                        loading={deletingId === scene.id}
                        onClick={() => {
                          Modal.confirm({
                            title: `彻底删除场景「${scene.name}」？`,
                            content: '这会删除场景资产本体，不是仅从当前项目移除。',
                            okText: '彻底删除',
                            cancelText: '取消',
                            okButtonProps: { danger: true },
                            onOk: () => handleDeleteScene(scene),
                          })
                        }}
                      >
                        彻底删除
                      </Button>
                    </Space>
                  }
                  meta={
                    <div className="space-y-1">
                      <div className="text-xs text-gray-600 line-clamp-2">{scene.description ?? '—'}</div>
                      <div className="text-xs text-gray-500 truncate">scene_id：{scene.id}</div>
                    </div>
                  }
                />
              )
            })}
            </div>
            <div className="flex justify-end">
              <Pagination
                current={page}
                pageSize={pageSize}
                total={visibleScenes.length}
                showSizeChanger={false}
                showTotal={(t) => `共 ${t} 条`}
                onChange={(p, ps) => {
                  setPage(p)
                  setPageSize(ps)
                }}
              />
            </div>
          </div>
        )}
      </Card>

      <StudioAssetTypeFormModal
        open={createModalOpen}
        label="场景"
        entityType="scene"
        editing={null}
        linkProjectId={projectId}
        createAsset={async (payload) => {
          const res = await StudioEntitiesApi.create('scene', payload as Record<string, unknown>)
          if (!res.data) throw new Error('empty scene')
          return res.data as SceneLike
        }}
        updateAsset={async (id, payload) => {
          const res = await StudioEntitiesApi.update('scene', id, payload as Record<string, unknown>)
          if (!res.data) throw new Error('empty scene')
          return res.data as SceneLike
        }}
        onCancel={() => setCreateModalOpen(false)}
        onSaved={async () => {
          await loadLinks()
        }}
      />

      <Modal
        title="从资产库关联场景"
        open={linkModalOpen}
        onCancel={() => setLinkModalOpen(false)}
        footer={null}
        width={560}
      >
        <div className="mb-3">
          <Input.Search
            placeholder="搜索场景名称"
            allowClear
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onSearch={(value) => loadScenes(value)}
          />
        </div>
        <div className="max-h-[60vh] overflow-y-auto">
          {scenesLoading ? (
            <div className="py-8 text-center text-gray-500">加载中...</div>
          ) : availableScenes.length === 0 ? (
            <Empty description={scenes.length === 0 ? '暂无场景，请先在资产管理中创建场景' : '当前项目已关联全部搜索结果'} />
          ) : (
            <div className="space-y-2">
              {availableScenes.map((scene) => (
                <div
                  key={scene.id}
                  className="flex items-center justify-between gap-3 rounded border border-gray-200 p-2 hover:bg-gray-50"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    {toThumbUrl(scene.thumbnail) ? (
                      <img
                        src={toThumbUrl(scene.thumbnail)}
                        alt=""
                        className="w-10 h-10 rounded object-cover shrink-0"
                      />
                    ) : (
                      <div className="w-10 h-10 rounded bg-gray-100 flex items-center justify-center text-gray-400 shrink-0">
                        —
                      </div>
                    )}
                    <div className="min-w-0">
                      <div className="font-medium truncate">{scene.name}</div>
                      {scene.description && <div className="text-xs text-gray-500 truncate">{scene.description}</div>}
                    </div>
                  </div>
                  <Button type="primary" size="small" loading={linkingId === scene.id} onClick={() => handleLinkScene(scene)}>
                    关联到项目
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>
      </Modal>
    </div>
  )
}
