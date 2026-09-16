import React, { useState } from 'react'
import { Button, Card } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { OrderList } from './OrderList'
import { TakeoutForm } from './TakeoutForm'
import { DeliveryForm } from './DeliveryForm'

export const OrdersPage: React.FC = () => {
  const [takeoutModalOpen, setTakeoutModalOpen] = useState(false)
  const [deliveryModalOpen, setDeliveryModalOpen] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)

  const handleSuccess = () => {
    setTakeoutModalOpen(false)
    setDeliveryModalOpen(false)
    setRefreshKey(prev => prev + 1)
  }

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
            Quản lý đơn hàng
          </h2>
          <p style={{ margin: '8px 0 0 0', color: 'rgba(0, 0, 0, 0.45)', fontSize: '14px' }}>
            Quản lý các đơn hàng mang về và giao hàng
          </p>
        </div>
        <div style={{ display: 'flex', gap: '12px' }}>
          <Button 
            type="primary" 
            size="large"
            icon={<PlusOutlined />} 
            onClick={() => setTakeoutModalOpen(true)}
            style={{ borderRadius: '6px' }}
          >
            Đơn mang về
          </Button>
          <Button 
            type="primary" 
            size="large"
            icon={<PlusOutlined />} 
            onClick={() => setDeliveryModalOpen(true)}
            style={{ borderRadius: '6px' }}
          >
            Đơn giao hàng
          </Button>
        </div>
      </div>

      <Card>
        <OrderList key={`${refreshKey}`} />
      </Card>

      <TakeoutForm
        open={takeoutModalOpen}
        onCancel={() => setTakeoutModalOpen(false)}
        onSuccess={handleSuccess}
      />

      <DeliveryForm
        open={deliveryModalOpen}
        onCancel={() => setDeliveryModalOpen(false)}
        onSuccess={handleSuccess}
      />
    </div>
  )
}
