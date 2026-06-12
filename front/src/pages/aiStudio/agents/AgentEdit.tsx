import { Empty, Button } from 'antd'
import { RobotOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { ArrowLeftOutlined } from '@ant-design/icons'

export default function AgentEdit() {
  const navigate = useNavigate()
  return (
    <div style={{ padding: 24 }}>
      <Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/agents')} style={{ marginBottom: 16 }}>
        返回列表
      </Button>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 360 }}>
        <Empty
          image={<RobotOutlined style={{ fontSize: 64, color: '#d9d9d9' }} />}
          imageStyle={{ height: 80 }}
          description={
            <div>
              <div style={{ fontSize: 16, fontWeight: 500, color: '#595959', marginBottom: 8 }}>Agent 编辑器</div>
              <div style={{ color: '#8c8c8c', fontSize: 14 }}>功能开发中，敬请期待</div>
            </div>
          }
        />
      </div>
    </div>
  )
}
