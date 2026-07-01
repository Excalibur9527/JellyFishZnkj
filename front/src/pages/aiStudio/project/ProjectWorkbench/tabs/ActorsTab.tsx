import { useEffect, useMemo, useState } from 'react'
import { Button, Card, Empty, Image, Input, Modal, Space, Tag, message, Pagination } from 'antd'
import { DeleteOutlined, EditOutlined, LinkOutlined, PlusOutlined, UserOutlined } from '@ant-design/icons'
import { useParams, useNavigate } from 'react-router-dom'
import { StudioShotLinksService } from '../../../../../services/generated'
import type { ProjectActorLinkRead } from '../../../../../services/generated'
import { StudioEntitiesApi } from '../../../../../services/studioEntities'
import { useProjectCharacters } from '../hooks/useProjectData'
import { resolveAssetUrl } from '../../../assets/utils'
import { DisplayImageCard } from '../../../assets/components/DisplayImageCard'
import { ActorEntityFormModal } from '../../../assets/components/ActorEntityFormModal'
import { encodeWorkbenchAssetEditReturnTo } from '../utils/workbenchAssetReturnTo'

type ActorLike = {
  id: string
  name: string
  description?: string | null
  thumbnail?: string
  tags?: string[]
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

export function ActorsTab() {
  const navigate = useNavigate()
  const { projectId } = useParams<{ projectId: string }>()
  useProjectCharacters(projectId)

  const [createModalOpen, setCreateModalOpen] = useState(false)
  const [linkModalOpen, setLinkModalOpen] = useState(false)
  const [actors, setActors] = useState<ActorLike[]>([])
  const [actorsLoading, setActorsLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [linkingId, setLinkingId] = useState<string | null>(null)
  const [unlinkingId, setUnlinkingId] = useState<number | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [links, setLinks] = useState<ProjectActorLinkRead[]>([])
  const [linksLoading, setLinksLoading] = useState(false)

  const linkedActorIdSet = useMemo(
    () => new Set(links.map((l) => l.actor_id).filter(Boolean) as string[]),
    [links],
  )

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(12)

  const uniqueLinks = useMemo(() => {
    const seen = new Map<string, ProjectActorLinkRead & { allLinkIds: number[] }>()
    for (const l of links) {
      if (seen.has(l.actor_id)) {
        seen.get(l.actor_id)!.allLinkIds.push(l.id)
      } else {
        seen.set(l.actor_id, { ...l, allLinkIds: [l.id] })
      }
    }
    return Array.from(seen.values())
  }, [links])

  const actorLinkByActorId = useMemo(() => {
    const map = new Map<string, ProjectActorLinkRead & { allLinkIds: number[] }>()
    uniqueLinks.forEach((link) => map.set(link.actor_id, link))
    return map
  }, [uniqueLinks])

  const visibleActors = useMemo(() => {
    const linkedActors = uniqueLinks
      .map((link) => actors.find((actor) => actor.id === link.actor_id))
      .filter(Boolean) as ActorLike[]
    const unlinkedActors = actors.filter((actor) => !linkedActorIdSet.has(actor.id))
    return [...linkedActors, ...unlinkedActors]
  }, [actors, linkedActorIdSet, uniqueLinks])

  const pagedActors = useMemo(() => {
    const start = (page - 1) * pageSize
    return visibleActors.slice(start, start + pageSize)
  }, [visibleActors, page, pageSize])

  useEffect(() => {
    setPage(1)
  }, [visibleActors.length])

  const loadLinks = async () => {
    if (!projectId) return
    setLinksLoading(true)
    try {
      const res = await StudioShotLinksService.listProjectEntityLinksApiV1StudioShotLinksEntityTypeGet({
        entityType: 'actor',
        projectId,
        chapterId: null,
        shotId: null,
        assetId: null,
        order: null,
        isDesc: false,
        page: 1,
        pageSize: 100,
      })
      setLinks((res.data?.items ?? []) as ProjectActorLinkRead[])
    } catch {
      message.error('加载项目演员关联失败')
      setLinks([])
    } finally {
      setLinksLoading(false)
    }
  }

  const loadActors = async (searchQuery?: string) => {
    setActorsLoading(true)
    try {
      const q = searchQuery !== undefined ? searchQuery : search
      const res = await StudioEntitiesApi.list('actor', {
        page: 1,
        pageSize: 100,
        q: q?.trim() || undefined,
        order: 'updated_at',
        isDesc: true,
      })
      setActors((res.data?.items ?? []) as ActorLike[])
    } catch {
      message.error('加载演员失败')
      setActors([])
    } finally {
      setActorsLoading(false)
    }
  }

  useEffect(() => {
    void loadActors('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  useEffect(() => {
    if (linkModalOpen) void loadActors('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linkModalOpen])

  useEffect(() => {
    void loadLinks()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  const handleLinkActor = async (actor: ActorLike) => {
    if (!projectId) return
    setLinkingId(actor.id)
    try {
      await StudioShotLinksService.createProjectActorLinkApiV1StudioShotLinksActorPost({
        requestBody: {
          project_id: projectId,
          chapter_id: null,
          shot_id: null,
          asset_id: actor.id,
        },
      })
      message.success(`已关联演员「${actor.name}」到项目`)
      setLinkModalOpen(false)
      await loadLinks()
    } catch (e: unknown) {
      const msg =
        e && typeof e === 'object' && 'body' in e && typeof (e as { body?: { detail?: string } }).body?.detail === 'string'
          ? (e as { body: { detail: string } }).body.detail
          : '关联失败'
      message.error(msg)
    } finally {
      setLinkingId(null)
    }
  }

  const handleUnlinkActor = async (link: ProjectActorLinkRead & { allLinkIds: number[] }) => {
    setUnlinkingId(link.id)
    try {
      await Promise.all(
        link.allLinkIds.map((id) =>
          StudioShotLinksService.deleteProjectActorLinkApiV1StudioShotLinksActorLinkIdDelete({ linkId: id }),
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

  const handleDeleteActor = async (actor: ActorLike) => {
    setDeletingId(actor.id)
    try {
      await StudioEntitiesApi.remove('actor', actor.id)
      message.success(`已删除演员「${actor.name}」`)
      await Promise.all([loadLinks(), loadActors('')])
    } catch (error) {
      message.error(getApiErrorDetail(error, '删除失败'))
    } finally {
      setDeletingId(null)
    }
  }

  const availableActors = useMemo(
    () => actors.filter((a) => !linkedActorIdSet.has(a.id)),
    [actors, linkedActorIdSet],
  )

  if (!projectId) return null

  return (
    <div className="h-full overflow-auto">
      <Card
        title="项目演员"
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
            <Button icon={<PlusOutlined />} onClick={() => navigate('/assets')}>
              前往资产管理
            </Button>
          </Space>
        }
      >
        {visibleActors.length === 0 && !linksLoading && !actorsLoading ? (
          <Empty description="暂无演员资产，可先新建或从资产库补充" image={Empty.PRESENTED_IMAGE_SIMPLE}>
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
              <Button onClick={() => navigate('/assets')}>前往资产管理</Button>
            </Space>
          </Empty>
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {pagedActors.map((actor) => {
              const link = actorLinkByActorId.get(actor.id)
              const isLinked = Boolean(link)
              return (
                <DisplayImageCard
                  key={actor.id}
                  title={
                    <div className="flex items-center gap-2 min-w-0">
                      <div className="truncate">{actor.name}</div>
                      <Tag color={isLinked ? 'green' : 'default'} className="shrink-0">
                        {isLinked ? '已关联' : '未关联'}
                      </Tag>
                    </div>
                  }
                  imageUrl={resolveAssetUrl(actor.thumbnail)}
                  imageAlt={actor.name}
                  extra={
                    <Space size="small">
                      <Button
                        type="default"
                        size="small"
                        icon={<EditOutlined />}
                        onClick={() =>
                          navigate(
                            `/assets/actors/${actor.id}/edit?returnTo=${encodeWorkbenchAssetEditReturnTo(projectId, 'actors')}`,
                          )
                        }
                      >
                        编辑
                      </Button>
                      {isLinked && link ? (
                        <>
                          <Button
                            size="small"
                            danger
                            loading={unlinkingId === link.id}
                            onClick={() => {
                              Modal.confirm({
                                title: `从当前项目移除「${actor.name}」？`,
                                okText: '从项目移除',
                                cancelText: '取消',
                                okButtonProps: { danger: true },
                                onOk: () => handleUnlinkActor(link),
                              })
                            }}
                          >
                            从项目移除
                          </Button>
                          <Button
                            size="small"
                            icon={<DeleteOutlined />}
                            loading={deletingId === actor.id}
                            onClick={() => {
                              Modal.confirm({
                                title: `彻底删除演员「${actor.name}」？`,
                                content: '这会删除演员资产本体，不是仅从当前项目移除。',
                                okText: '彻底删除',
                                cancelText: '取消',
                                okButtonProps: { danger: true },
                                onOk: () => handleDeleteActor(actor),
                              })
                            }}
                          >
                            彻底删除
                          </Button>
                        </>
                      ) : (
                        <>
                          <Button
                            type="primary"
                            size="small"
                            loading={linkingId === actor.id}
                            onClick={() => handleLinkActor(actor)}
                          >
                            关联到项目
                          </Button>
                          <Button
                            size="small"
                            icon={<DeleteOutlined />}
                            loading={deletingId === actor.id}
                            onClick={() => {
                              Modal.confirm({
                                title: `彻底删除演员「${actor.name}」？`,
                                content: '这会删除演员资产本体，不是仅从当前项目移除。',
                                okText: '彻底删除',
                                cancelText: '取消',
                                okButtonProps: { danger: true },
                                onOk: () => handleDeleteActor(actor),
                              })
                            }}
                          >
                            彻底删除
                          </Button>
                        </>
                      )}
                    </Space>
                  }
                  meta={
                    <div className="space-y-1">
                      <div className="text-xs text-gray-600 line-clamp-2">{actor.description ?? '—'}</div>
                      <div className="text-xs text-gray-500 truncate">actor_id：{actor.id}</div>
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
                total={visibleActors.length}
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

      <ActorEntityFormModal
        open={createModalOpen}
        editing={null}
        linkProjectId={projectId}
        onCancel={() => setCreateModalOpen(false)}
        onSuccess={async () => {
          await loadLinks()
        }}
      />

      <Modal
        title="从资产库关联演员"
        open={linkModalOpen}
        onCancel={() => setLinkModalOpen(false)}
        footer={null}
        width={560}
      >
        <div className="mb-3">
          <Input.Search
            placeholder="搜索演员名称"
            allowClear
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onSearch={(value) => loadActors(value)}
          />
        </div>
        <div className="max-h-[60vh] overflow-y-auto">
          {actorsLoading ? (
            <div className="py-8 text-center text-gray-500">加载中...</div>
          ) : availableActors.length === 0 ? (
            <Empty description={actors.length === 0 ? '暂无演员，请先在资产管理中创建演员' : '当前项目已关联全部搜索结果'} />
          ) : (
            <div className="space-y-2">
              {availableActors.map((actor) => (
                <div
                  key={actor.id}
                  className="flex items-center justify-between gap-3 rounded border border-gray-200 p-2 hover:bg-gray-50"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    {resolveAssetUrl(actor.thumbnail) ? (
                      <Image
                        src={resolveAssetUrl(actor.thumbnail)}
                        alt=""
                        width={40}
                        height={40}
                        style={{ objectFit: 'cover', borderRadius: 4 }}
                      />
                    ) : (
                      <div className="w-10 h-10 rounded bg-gray-100 flex items-center justify-center text-gray-400 shrink-0">
                        <UserOutlined />
                      </div>
                    )}
                    <div className="min-w-0">
                      <div className="font-medium truncate">{actor.name}</div>
                      {actor.description && <div className="text-xs text-gray-500 truncate">{actor.description}</div>}
                    </div>
                  </div>
                  <Button
                    type="primary"
                    size="small"
                    loading={linkingId === actor.id}
                    onClick={() => handleLinkActor(actor)}
                  >
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
