import React, { useState } from 'react'
import { Button, Card } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { BookingList } from './BookingList'
import { BookingForm } from './BookingForm'
import { Booking } from '../../types'

export const BookingsPage: React.FC = () => {
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [editingBooking, setEditingBooking] = useState<Booking | null>(null)

  const handleCreate = () => {
    setEditingBooking(null)
    setIsModalOpen(true)
  }

  const handleEdit = (booking: Booking) => {
    setEditingBooking(booking)
    setIsModalOpen(true)
  }

  const handleCancel = () => {
    setIsModalOpen(false)
    setEditingBooking(null)
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
            Quản lý đặt bàn
          </h2>
          <p style={{ margin: '8px 0 0 0', color: 'rgba(0, 0, 0, 0.45)', fontSize: '14px' }}>
            Theo dõi và quản lý các đặt bàn từ khách hàng
          </p>
        </div>
        <Button 
          type="primary" 
          size="large"
          icon={<PlusOutlined />} 
          onClick={handleCreate}
          style={{ borderRadius: '6px' }}
        >
          Thêm đặt bàn
        </Button>
      </div>

      <Card>
        <BookingList onEdit={handleEdit} />
      </Card>

      <BookingForm
        open={isModalOpen}
        onCancel={handleCancel}
        initialData={editingBooking}
      />
    </div>
  )
}
