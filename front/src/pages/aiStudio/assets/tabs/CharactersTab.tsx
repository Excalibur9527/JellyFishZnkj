import { useEffect, useMemo, useState } from 'react'
import { Button, Card, Empty, Input, Modal, Pagination, Space, Tag, message } from 'antd'
import { DeleteOutlined, EditOutlined, ReloadOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { StudioEntitiesApi } from '../../../../services/studioEntities'
import { DisplayImageCard } from '../components/DisplayImageCard'
import { resolveAssetUrl } from '../utils'

type CharacterLike = {
  id: string
  project_id?: string
  name: string
  description?: string | null
  thumbnail?: string
  actor_id?: string | null
  costume_id?: string | null
}

export function CharactersTab() {
  const navigate = useNavigate()
  const [characters, setCharacters] = useState<CharacterLike[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(12)
  const [total, setTotal] = useState(0)

  const load = async (opts?: { page?: number; pageSize?: number; q?: string }) => {
    setLoading(true)
    try {
      const nextPage = opts?.page ?? page
      const nextPageSize = opts?.pageSize ?? pageSize
      const q = typeof opts?.q === 'string' ? opts.q : search.trim() || undefined
      const res = await StudioEntitiesApi.list('character', {
        page: nextPage,
        pageSize: nextPageSize,
        q: q ?? null,
        order: 'updated_at',
        isDesc: true,
      })
      setCharacters((res.data?.items ?? []) as CharacterLike[])
      setTotal(res.data?.pagination.total ?? 0)
    } catch {
      message.error('加载角色失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize])

  const filtered = useMemo(() => characters, [characters])

  return (
    <Card
      title="角色"
      extra={
        <Space>
          <Input.Search
            placeholder="搜索角色"
            allowClear
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onSearch={(v) => {
              setPage(1)
              void load({ q: v, page: 1 })
            }}
            style={{ width: 240 }}
          />
          <Button icon={<ReloadOutlined />} onClick={() => void load()}>
            刷新
          </Button>
        </Space>
      }
    >
      {filtered.length === 0 && !loading ? (
        <Empty description="暂无角色。角色属于项目资产，请优先在项目工作台的「角色」中创建。" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {filtered.map((character) => (
            <DisplayImageCard
              key={character.id}
              title={<div className="truncate">{character.name}</div>}
              imageUrl={resolveAssetUrl(character.thumbnail)}
              imageAlt={character.name}
              extra={
                <Space>
                  <Button size="small" icon={<EditOutlined />} onClick={() => navigate(`/assets/characters/${character.id}/edit`)}>
                    编辑
                  </Button>
                  <Button
                    danger
                    size="small"
                    icon={<DeleteOutlined />}
                    onClick={() => {
                      Modal.confirm({
                        title: `删除角色「${character.name}」？`,
                        content: '角色通常属于具体项目；删除后会影响分镜关联与后续生成。',
                        okText: '删除',
                        cancelText: '取消',
                        okButtonProps: { danger: true },
                        onOk: async () => {
                          try {
                            await StudioEntitiesApi.remove('character', character.id)
                            message.success('已删除')
                            void load()
                          } catch {
                            message.error('删除角色失败')
                          }
                        },
                      })
                    }}
                  />
                </Space>
              }
              meta={
                <div>
                  {character.description ? <div className="text-xs text-gray-600 line-clamp-2">{character.description}</div> : null}
                  <div className="mt-2 flex flex-wrap gap-1">
                    {character.actor_id ? <Tag className="m-0">演员已关联</Tag> : null}
                    {character.costume_id ? <Tag className="m-0">服装已关联</Tag> : null}
                  </div>
                </div>
              }
            />
          ))}
        </div>
      )}

      <div className="mt-4 flex justify-end">
        <Pagination
          current={page}
          pageSize={pageSize}
          total={total}
          showSizeChanger={false}
          onChange={(p, ps) => {
            setPage(p)
            setPageSize(ps)
          }}
        />
      </div>
    </Card>
  )
}
