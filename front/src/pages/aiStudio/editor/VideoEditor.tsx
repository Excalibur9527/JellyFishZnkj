import React, { useEffect, useState, useCallback, useMemo } from 'react'
import { Card, Button, message, Tag, Empty, Spin, Image } from 'antd'
import {
  ExportOutlined,
  ArrowLeftOutlined,
  VideoCameraOutlined,
  FileImageOutlined,
} from '@ant-design/icons'
import { useParams, Link } from 'react-router-dom'
import { StudioFilesService } from '../../../services/generated/services/StudioFilesService'
import { OpenAPI } from '../../../services/generated/core/OpenAPI'
import type { FileRead } from '../../../services/generated/models/FileRead'

const VideoEditor: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>()
  const [files, setFiles] = useState<FileRead[]>([])
  const [loading, setLoading] = useState(true)

  const backendBase = useMemo(() => (OpenAPI.BASE || '').replace(/\/$/, ''), [])
  const fileUrl = useCallback((id: string) => `${backendBase}/api/v1/studio/files/${id}/download`, [backendBase])

  useEffect(() => {
    if (!projectId) { setLoading(false); return }
    setLoading(true)
    void StudioFilesService.listFilesApiApiV1StudioFilesGet({
      projectId,
      order: 'updated_at',
      isDesc: true,
      page: 1,
      pageSize: 100,
    })
      .then((res) => setFiles(res.data?.items ?? []))
      .catch(() => message.error('加载素材失败'))
      .finally(() => setLoading(false))
  }, [projectId])

  const videos = files.filter(f => f.type === 'video')
  const images = files.filter(f => f.type === 'image')

  return (
    <div style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div>
        <Link
          to={projectId ? `/projects/${projectId}/chapters` : '/projects'}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: '#595959', fontSize: 13 }}
        >
          <ArrowLeftOutlined /> {projectId ? '返回章节列表' : '项目列表'}
        </Link>
      </div>

      <Card
        title="视频编辑器"
        extra={
          <Button icon={<ExportOutlined />} disabled>
            导出成片（开发中）
          </Button>
        }
      >
        <div style={{
          background: '#141414',
          borderRadius: 8,
          padding: 24,
          minHeight: 300,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          marginBottom: 16,
          color: '#595959',
          fontSize: 14,
        }}>
          视频合成编辑器 · 开发中
        </div>

        {loading ? (
          <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
        ) : (
          <>
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontWeight: 500, marginBottom: 8, color: '#262626' }}>
                <Tag color="blue" icon={<VideoCameraOutlined />}>视频素材</Tag>
                共 {videos.length} 个
              </div>
              {videos.length === 0 ? (
                <Empty description="暂无视频素材" imageStyle={{ height: 40 }} />
              ) : (
                <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                  {videos.map(f => (
                    <div key={f.id} style={{
                      width: 180,
                      background: '#000',
                      borderRadius: 6,
                      overflow: 'hidden',
                      border: '1px solid #303030',
                    }}>
                      <video
                        src={fileUrl(f.id)}
                        style={{ width: '100%', height: 100, objectFit: 'cover', display: 'block' }}
                        controls={false}
                        preload="metadata"
                        muted
                      />
                      <div style={{ padding: '4px 8px', fontSize: 11, color: '#8c8c8c', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={f.name}>
                        {f.name}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div>
              <div style={{ fontWeight: 500, marginBottom: 8, color: '#262626' }}>
                <Tag color="green" icon={<FileImageOutlined />}>图片素材</Tag>
                共 {images.length} 个
              </div>
              {images.length === 0 ? (
                <Empty description="暂无图片素材" imageStyle={{ height: 40 }} />
              ) : (
                <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                  {images.map(f => (
                    <div key={f.id} style={{
                      width: 120,
                      borderRadius: 6,
                      overflow: 'hidden',
                      border: '1px solid #f0f0f0',
                    }}>
                      <Image
                        src={fileUrl(f.id)}
                        style={{ width: 120, height: 80, objectFit: 'cover', display: 'block' }}
                        preview={false}
                        fallback="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
                      />
                      <div style={{ padding: '4px 6px', fontSize: 11, color: '#8c8c8c', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={f.name}>
                        {f.name}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </Card>
    </div>
  )
}

export default VideoEditor
