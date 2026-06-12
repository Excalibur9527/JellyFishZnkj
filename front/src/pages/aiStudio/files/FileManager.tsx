import React, { useEffect, useState, useCallback, useMemo } from 'react'
import { Input, Tag, Button, message, Pagination, Image, Select, Popconfirm, Spin } from 'antd'
import { DownloadOutlined, ReloadOutlined, DeleteOutlined, VideoCameraOutlined, FileImageOutlined } from '@ant-design/icons'
import { StudioFilesService } from '../../../services/generated/services/StudioFilesService'
import { StudioProjectsService } from '../../../services/generated/services/StudioProjectsService'
import { OpenAPI } from '../../../services/generated/core/OpenAPI'
import type { FileRead } from '../../../services/generated/models/FileRead'

const FileManager: React.FC = () => {
  const [files, setFiles] = useState<FileRead[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState<string | undefined>(undefined)
  const [projectId, setProjectId] = useState<string | undefined>(undefined)
  const [projects, setProjects] = useState<Array<{ id: string; name: string }>>([])
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const pageSize = 20

  const backendBase = useMemo(() => (OpenAPI.BASE || '').replace(/\/$/, ''), [])
  const fileUrl = useCallback((id: string) => `${backendBase}/api/v1/studio/files/${id}/download`, [backendBase])

  useEffect(() => {
    void StudioProjectsService.listProjectsApiV1StudioProjectsGet({ page: 1, pageSize: 100 })
      .then((res) => {
        const items = (res.data?.items ?? []) as Array<{ id: string; name: string }>
        setProjects(items.map(p => ({ id: p.id, name: p.name })))
      })
      .catch(() => {})
  }, [])

  const load = useCallback(async (currentPage: number, q?: string, pid?: string) => {
    setLoading(true)
    try {
      const res = await StudioFilesService.listFilesApiApiV1StudioFilesGet({
        q: q || undefined,
        order: 'updated_at',
        isDesc: true,
        page: currentPage,
        pageSize,
        projectId: pid || undefined,
      })
      setFiles(res.data?.items ?? [])
      setTotal(res.data?.pagination?.total ?? 0)
    } catch {
      message.error('加载文件失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load(1, '', undefined) }, [load])

  const handleSearch = (value: string) => {
    setSearch(value); setPage(1); void load(1, value, projectId)
  }
  const handleProjectChange = (value: string | undefined) => {
    setProjectId(value); setPage(1); void load(1, search, value)
  }
  const handleDelete = async (id: string) => {
    try {
      await StudioFilesService.deleteFileApiApiV1StudioFilesFileIdDelete({ fileId: id })
      message.success('已删除')
      void load(page, search, projectId)
    } catch {
      message.error('删除失败')
    }
  }

  const filtered = typeFilter ? files.filter(f => f.type === typeFilter) : files

  return (
    <div style={{ padding: 24 }}>
      {/* 筛选栏 */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap', alignItems: 'center' }}>
        <Input.Search
          placeholder="搜索文件名"
          allowClear
          style={{ width: 220 }}
          onSearch={handleSearch}
          onChange={(e) => { if (!e.target.value) handleSearch('') }}
        />
        <Select
          placeholder="按项目筛选"
          allowClear
          style={{ width: 180 }}
          value={projectId}
          onChange={handleProjectChange}
          options={projects.map(p => ({ label: p.name, value: p.id }))}
        />
        <Select
          placeholder="文件类型"
          allowClear
          style={{ width: 120 }}
          value={typeFilter}
          onChange={(v) => setTypeFilter(v)}
          options={[
            { label: '🖼 图片', value: 'image' },
            { label: '🎬 视频', value: 'video' },
          ]}
        />
        <Button icon={<ReloadOutlined />} onClick={() => void load(page, search, projectId)}>刷新</Button>
        <span style={{ color: '#999', fontSize: 13, marginLeft: 'auto' }}>共 {total} 个文件</span>
      </div>

      {/* 文件网格 */}
      {loading ? (
        <div style={{ textAlign: 'center', padding: 60 }}><Spin size="large" /></div>
      ) : filtered.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 60, color: '#999' }}>暂无文件</div>
      ) : (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
          gap: 16,
        }}>
          {filtered.map((f) => (
            <div key={f.id} style={{
              background: '#fff',
              borderRadius: 8,
              border: '1px solid #f0f0f0',
              overflow: 'hidden',
              boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
              transition: 'box-shadow 0.2s',
            }}
              onMouseEnter={e => (e.currentTarget.style.boxShadow = '0 4px 12px rgba(0,0,0,0.12)')}
              onMouseLeave={e => (e.currentTarget.style.boxShadow = '0 1px 4px rgba(0,0,0,0.06)')}
            >
              {/* 预览区 - 固定高度 */}
              <div style={{ width: '100%', height: 160, background: '#000', position: 'relative', overflow: 'hidden' }}>
                {f.type === 'image' ? (
                  <Image
                    src={fileUrl(f.id)}
                    alt={f.name}
                    style={{ width: '100%', height: 160, objectFit: 'cover', display: 'block' }}
                    preview={{ mask: '预览' }}
                    fallback="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
                  />
                ) : (
                  <video
                    src={fileUrl(f.id)}
                    style={{ width: '100%', height: 160, objectFit: 'cover', display: 'block' }}
                    controls
                    preload="metadata"
                  />
                )}
              </div>

              {/* 信息区 */}
              <div style={{ padding: '10px 12px 8px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                  {f.type === 'video'
                    ? <Tag color="blue" style={{ margin: 0 }} icon={<VideoCameraOutlined />}>视频</Tag>
                    : <Tag color="green" style={{ margin: 0 }} icon={<FileImageOutlined />}>图片</Tag>
                  }
                </div>
                <div style={{
                  fontSize: 12,
                  color: '#333',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  marginBottom: 8,
                }} title={f.name}>
                  {f.name}
                </div>
                <div style={{ display: 'flex', gap: 4 }}>
                  <Button
                    type="default"
                    size="small"
                    icon={<DownloadOutlined />}
                    href={fileUrl(f.id)}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ flex: 1, fontSize: 12 }}
                  >
                    下载
                  </Button>
                  <Popconfirm
                    title="确认删除此文件？"
                    okText="删除"
                    cancelText="取消"
                    okButtonProps={{ danger: true }}
                    onConfirm={() => void handleDelete(f.id)}
                  >
                    <Button danger size="small" icon={<DeleteOutlined />} style={{ fontSize: 12 }} />
                  </Popconfirm>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {total > pageSize && (
        <div style={{ marginTop: 24, display: 'flex', justifyContent: 'flex-end' }}>
          <Pagination
            current={page}
            pageSize={pageSize}
            total={total}
            onChange={(p) => { setPage(p); void load(p, search, projectId) }}
            showSizeChanger={false}
          />
        </div>
      )}
    </div>
  )
}

export default FileManager
