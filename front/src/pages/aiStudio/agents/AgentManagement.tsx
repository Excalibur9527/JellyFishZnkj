import { Empty, Button } from 'antd'
import { RobotOutlined } from '@ant-design/icons'

export default function AgentManagement() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 400 }}>
      <Empty
        image={<RobotOutlined style={{ fontSize: 64, color: '#d9d9d9' }} />}
        imageStyle={{ height: 80 }}
        description={
          <div>
            <div style={{ fontSize: 16, fontWeight: 500, color: '#595959', marginBottom: 8 }}>Agent 管理</div>
            <div style={{ color: '#8c8c8c', fontSize: 14 }}>功能开发中，敬请期待</div>
          </div>
        }
      >
        <Button disabled>创建 Agent（即将上线）</Button>
      </Empty>
    </div>
  )
}
