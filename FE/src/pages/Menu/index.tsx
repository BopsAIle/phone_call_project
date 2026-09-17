import React from 'react'
import { Card } from 'antd'
import { MenuList } from './MenuList'

export const MenuPage: React.FC = () => {

  return (
    <div>
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: '24px',
        paddingBottom: '16px',
        borderBottom: '1px solid #f0f0f0',
      }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '24px', fontWeight: 600, color: '#001529' }}>
            Quản lý thực đơn
          </h2>
          <p style={{ margin: '8px 0 0 0', color: 'rgba(0, 0, 0, 0.45)', fontSize: '14px' }}>
            Quản lý các món ăn và thực đơn của nhà hàng
          </p>
        </div>
      </div>

      <Card>
        <MenuList />
      </Card>
    </div>
  )
}
