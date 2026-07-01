import { useEffect, useMemo, useState } from 'react'
import { Button, Card, Empty, Input, Modal, Space, Tag, message, Pagination } from 'antd'
import { DeleteOutlined, EditOutlined, LinkOutlined, PlusOutlined } from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import { StudioShotLinksService } from '../../../../../services/generated'
import type { ProjectCostumeLinkRead, ProjectPropLinkRead } from '../../../../../services/generated'
import { resolveAssetUrl } from '../../../assets/utils'
import { DisplayImageCard } from '../../../assets/components/DisplayImageCard'
import { StudioEntitiesApi } from '../../../../../services/studioEntities'
import { StudioAssetTypeFormModal } from '../../../assets/components/StudioAssetTypeFormModal'
import { encodeWorkbenchAssetEditReturnTo, type WorkbenchAssetTabParam } from '../utils/workbenchAssetReturnTo'

type AssetKind = 'prop' | 'costume'

type AssetItemLike = {
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

function LinkedAssetTab({
  kind,
  projectId,
}: {
  kind: AssetKind
  projectId: string
}) {
  const navigate = useNavigate()
  const workbenchTab: WorkbenchAssetTabParam = kind === 'prop' ? 'props' : 'costumes'
  const [createModalOpen, setCreateModalOpen] = useState(false)
  const [linkModalOpen, setLinkModalOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(false)
  const [listLoading, setListLoading] = useState(false)
  const [linkingId, setLinkingId] = useState<string | null>(null)
  const [unlinkingId, setUnlinkingId] = useState<number | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const [links, setLinks] = useState<(ProjectPropLinkRead | ProjectCostumeLinkRead)[]>([])
  const [assets, setAssets] = useState<AssetItemLike[]>([])
  const [assetsById, setAssetsById] = useState<Record<string, AssetItemLike>>({})

  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(12)

  const uniqueLinks = useMemo(() => {
    const seen = new Map<string, (ProjectPropLinkRead | ProjectCostumeLinkRead) & { allLinkIds: number[] }>()
    for (const l of links) {
      const assetId = 'prop_id' in l ? l.prop_id : l.costume_id
      if (seen.has(assetId)) {
        seen.get(assetId)!.allLinkIds.push(l.id)
      } else {
        seen.set(assetId, { ...l, allLinkIds: [l.id] })
      }
    }
    return Array.from(seen.values())
  }, [links])

  const linkedIdSet = useMemo(
    () => new Set(links.map((l) => ('prop_id' in l ? l.prop_id : l.costume_id))),
    [links],
  )

  const linkByAssetId = useMemo(() => {
    const map = new Map<string, (ProjectPropLinkRead | ProjectCostumeLinkRead) & { allLinkIds: number[] }>()
    uniqueLinks.forEach((link) => {
      const assetId = 'prop_id' in link ? link.prop_id : link.costume_id
      map.set(assetId, link)
    })
    return map
  }, [uniqueLinks])

  const visibleAssets = useMemo(() => {
    const linkedAssets = uniqueLinks
      .map((link) => {
        const assetId = 'prop_id' in link ? link.prop_id : link.costume_id
        return assets.find((asset) => asset.id === assetId) ?? assetsById[assetId]
      })
      .filter(Boolean) as AssetItemLike[]
    const unlinkedAssets = assets.filter((asset) => !linkedIdSet.has(asset.id))
    return [...linkedAssets, ...unlinkedAssets]
  }, [assets, assetsById, linkedIdSet, uniqueLinks])

  const pagedAssets = useMemo(() => {
    const start = (page - 1) * pageSize
    return visibleAssets.slice(start, start + pageSize)
  }, [page, pageSize, visibleAssets])

  useEffect(() => {
    setPage(1)
  }, [visibleAssets.length])

  const loadLinks = async () => {
    setLoading(true)
    try {
      const res = await StudioShotLinksService.listProjectEntityLinksApiV1StudioShotLinksEntityTypeGet({
        entityType: kind,
        projectId,
        chapterId: null,
        shotId: null,
        assetId: null,
        order: null,
        isDesc: false,
        page: 1,
        pageSize: 100,
      })

      const items = (res.data?.items ?? []) as any[]
      const typedItems = items as (ProjectPropLinkRead | ProjectCostumeLinkRead)[]
      setLinks(typedItems)

      const ids = Array.from(new Set(items.map((l) => (kind === 'prop' ? l.prop_id : l.costume_id)).filter(Boolean))) as string[]

      const entityIdKey = kind === 'prop' ? 'prop' : 'costume'
      const detailList = await Promise.all(
        ids.map((id) =>
          StudioEntitiesApi.get(entityIdKey, id)
            .then((r) => (r.data ?? null) as AssetItemLike | null)
            .catch(() => null),
        ),
      )

      const map: Record<string, AssetItemLike> = {}
      detailList.filter(Boolean).forEach((x) => {
        map[x!.id] = x!
      })
      setAssetsById(map)
    } catch {
      message.error(`加载项目${kind === 'prop' ? '道具' : '服装'}关联失败`)
      setLinks([])
      setAssetsById({})
    } finally {
      setLoading(false)
    }
  }

  const loadAssets = async (qOverride?: string) => {
    setListLoading(true)
    try {
      const q = (qOverride ?? search).trim()
      const res =
        kind === 'prop'
          ? await StudioEntitiesApi.list('prop', {
              q: q || null,
              order: 'updated_at',
              isDesc: true,
              page: 1,
              pageSize: 100,
            })
          : await StudioEntitiesApi.list('costume', {
              q: q || null,
              order: 'updated_at',
              isDesc: true,
              page: 1,
              pageSize: 100,
            })
      setAssets((res.data?.items ?? []) as AssetItemLike[])
    } catch {
      message.error(`加载${kind === 'prop' ? '道具' : '服装'}失败`)
      setAssets([])
    } finally {
      setListLoading(false)
    }
  }

  useEffect(() => {
    void loadLinks()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, kind])

  useEffect(() => {
    void loadAssets('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, kind])

  useEffect(() => {
    if (linkModalOpen) void loadAssets('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linkModalOpen, kind])
  const available = useMemo(() => assets.filter((a) => !linkedIdSet.has(a.id)), [assets, linkedIdSet])

  const handleLink = async (assetId: string, assetName: string) => {
    setLinkingId(assetId)
    try {
      if (kind === 'prop') {
        await StudioShotLinksService.createProjectPropLinkApiV1StudioShotLinksPropPost({
          requestBody: { project_id: projectId, chapter_id: null, shot_id: null, asset_id: assetId },
        })
      } else {
        await StudioShotLinksService.createProjectCostumeLinkApiV1StudioShotLinksCostumePost({
          requestBody: { project_id: projectId, chapter_id: null, shot_id: null, asset_id: assetId },
        })
      }
      message.success(`已关联${kind === 'prop' ? '道具' : '服装'}「${assetName}」`)
      setLinkModalOpen(false)
      await loadLinks()
    } catch {
      message.error('关联失败')
    } finally {
      setLinkingId(null)
    }
  }

  const handleUnlink = async (link: (ProjectPropLinkRead | ProjectCostumeLinkRead) & { allLinkIds: number[] }) => {
    setUnlinkingId(link.id)
    try {
      await Promise.all(
        link.allLinkIds.map((id) =>
          'prop_id' in link
            ? StudioShotLinksService.deleteProjectPropLinkApiV1StudioShotLinksPropLinkIdDelete({ linkId: id })
            : StudioShotLinksService.deleteProjectCostumeLinkApiV1StudioShotLinksCostumeLinkIdDelete({ linkId: id }),
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

  const handleDelete = async (asset: AssetItemLike) => {
    setDeletingId(asset.id)
    try {
      await StudioEntitiesApi.remove(kind, asset.id)
      message.success(`已删除${kind === 'prop' ? '道具' : '服装'}「${asset.name}」`)
      await Promise.all([loadLinks(), loadAssets('')])
    } catch (error) {
      message.error(getApiErrorDetail(error, '删除失败'))
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <div className="h-full overflow-auto">
      <Card
        title={`项目${kind === 'prop' ? '道具' : '服装'}`}
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
            <Button icon={<PlusOutlined />} onClick={() => navigate(`/assets?tab=${kind}`)}>
              前往资产管理
            </Button>
          </Space>
        }
      >
        {visibleAssets.length === 0 && !loading && !listLoading ? (
          <Empty description={`暂无${kind === 'prop' ? '道具' : '服装'}资产，可先新建或从资产库补充`} image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {pagedAssets.map((asset) => {
              const link = linkByAssetId.get(asset.id)
              const isLinked = Boolean(link)
              const linkThumb = (link as any)?.thumbnail as string | undefined
              return (
                <DisplayImageCard
                  key={asset.id}
                  title={
                    <div className="flex items-center gap-2 min-w-0">
                      <div className="truncate">{asset.name}</div>
                      <Tag color={isLinked ? 'green' : 'default'} className="shrink-0">
                        {isLinked ? '已关联' : '未关联'}
                      </Tag>
                    </div>
                  }
                  imageUrl={resolveAssetUrl(linkThumb ?? asset.thumbnail)}
                  imageAlt={asset.name}
                  extra={
                    <Space size="small">
                      <Button
                        type="default"
                        size="small"
                        icon={<EditOutlined />}
                        onClick={() => {
                          const path =
                            kind === 'prop'
                              ? `/assets/props/${asset.id}/edit`
                              : `/assets/costumes/${asset.id}/edit`
                          navigate(`${path}?returnTo=${encodeWorkbenchAssetEditReturnTo(projectId, workbenchTab)}`)
                        }}
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
                              title: `从当前项目移除「${asset.name}」？`,
                              okText: '从项目移除',
                              cancelText: '取消',
                              okButtonProps: { danger: true },
                              onOk: () => handleUnlink(link),
                            })
                          }}
                        >
                          从项目移除
                        </Button>
                      ) : (
                        <Button type="primary" size="small" loading={linkingId === asset.id} onClick={() => handleLink(asset.id, asset.name)}>
                          关联到项目
                        </Button>
                      )}
                      <Button
                        size="small"
                        icon={<DeleteOutlined />}
                        loading={deletingId === asset.id}
                        onClick={() => {
                          Modal.confirm({
                            title: `彻底删除${kind === 'prop' ? '道具' : '服装'}「${asset.name}」？`,
                            content: `这会删除${kind === 'prop' ? '道具' : '服装'}资产本体，不是仅从当前项目移除。`,
                            okText: '彻底删除',
                            cancelText: '取消',
                            okButtonProps: { danger: true },
                            onOk: () => handleDelete(asset),
                          })
                        }}
                      >
                        彻底删除
                      </Button>
                    </Space>
                  }
                  meta={
                    <div className="space-y-1">
                      <div className="text-xs text-gray-600 line-clamp-2">{asset.description ?? '—'}</div>
                      <div className="text-xs text-gray-500 truncate">{`${kind}_id：${asset.id}`}</div>
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
                total={visibleAssets.length}
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
        label={kind === 'prop' ? '道具' : '服装'}
        entityType={kind}
        editing={null}
        linkProjectId={projectId}
        createAsset={async (payload) => {
          const entity = kind === 'prop' ? 'prop' : 'costume'
          const res = await StudioEntitiesApi.create(entity, payload as Record<string, unknown>)
          if (!res.data) throw new Error(`empty ${entity}`)
          return res.data as AssetItemLike
        }}
        updateAsset={async (id, payload) => {
          const entity = kind === 'prop' ? 'prop' : 'costume'
          const res = await StudioEntitiesApi.update(entity, id, payload as Record<string, unknown>)
          if (!res.data) throw new Error(`empty ${entity}`)
          return res.data as AssetItemLike
        }}
        onCancel={() => setCreateModalOpen(false)}
        onSaved={async () => {
          await loadLinks()
        }}
      />

      <Modal
        title={`从资产库关联${kind === 'prop' ? '道具' : '服装'}`}
        open={linkModalOpen}
        onCancel={() => setLinkModalOpen(false)}
        footer={null}
        width={560}
      >
        <div className="mb-3">
          <Input.Search
            placeholder={`搜索${kind === 'prop' ? '道具' : '服装'}名称`}
            allowClear
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onSearch={(v) => loadAssets(v)}
          />
        </div>
        <div className="max-h-[60vh] overflow-y-auto">
          {listLoading ? (
            <div className="py-8 text-center text-gray-500">加载中...</div>
          ) : available.length === 0 ? (
            <Empty description="暂无可关联资产" />
          ) : (
            <div className="space-y-2">
              {available.map((a) => (
                <div key={a.id} className="flex items-center justify-between gap-3 rounded border border-gray-200 p-2 hover:bg-gray-50">
                  <div className="flex items-center gap-2 min-w-0">
                    {resolveAssetUrl(a.thumbnail) ? (
                      <img src={resolveAssetUrl(a.thumbnail)} alt="" className="w-10 h-10 rounded object-cover shrink-0" />
                    ) : (
                      <div className="w-10 h-10 rounded bg-gray-100 flex items-center justify-center text-gray-400 shrink-0">—</div>
                    )}
                    <div className="min-w-0">
                      <div className="font-medium truncate">{a.name}</div>
                      {a.description ? <div className="text-xs text-gray-500 truncate">{a.description}</div> : null}
                    </div>
                  </div>
                  <Button type="primary" size="small" loading={linkingId === a.id} onClick={() => handleLink(a.id, a.name)}>
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

export function PropsTab() {
  const { projectId } = useParams<{ projectId: string }>()
  if (!projectId) return null
  return <LinkedAssetTab kind="prop" projectId={projectId} />
}

export function CostumesTab() {
  const { projectId } = useParams<{ projectId: string }>()
  if (!projectId) return null
  return <LinkedAssetTab kind="costume" projectId={projectId} />
}
