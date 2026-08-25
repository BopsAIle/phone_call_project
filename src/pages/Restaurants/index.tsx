import React, { useState } from 'react'
import { Button, Card } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { RestaurantList } from './RestaurantList'
import { RestaurantForm } from './RestaurantForm'
import { RestaurantDetail } from './RestaurantDetail'
import { Restaurant } from '../../types'

export const RestaurantsPage: React.FC = () => {
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [editingRestaurant, setEditingRestaurant] = useState<Restaurant | null>(null)
  const [viewingRestaurant, setViewingRestaurant] = useState<Restaurant | null>(null)

  const handleCreate = () => {
    setEditingRestaurant(null)
    setIsModalOpen(true)
  }

  const handleEdit = (restaurant: Restaurant) => {
    setEditingRestaurant(restaurant)
    setIsModalOpen(true)
  }

  const handleView = (restaurant: Restaurant) => {
    setViewingRestaurant(restaurant)
  }

  const handleCancel = () => {
    setIsModalOpen(false)
    setEditingRestaurant(null)
  }

  const handleBackFromDetail = () => {
    setViewingRestaurant(null)
  }

  if (viewingRestaurant) {
    return (
      <RestaurantDetail
        restaurant={viewingRestaurant}
        onBack={handleBackFromDetail}
      />
    )
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
            Quản lý nhà hàng
          </h2>
          <p style={{ margin: '8px 0 0 0', color: 'rgba(0, 0, 0, 0.45)', fontSize: '14px' }}>
            Quản lý và theo dõi tất cả nhà hàng trong hệ thống
          </p>
        </div>
        <Button 
          type="primary" 
          size="large"
          icon={<PlusOutlined />} 
          onClick={handleCreate}
          style={{ borderRadius: '6px' }}
        >
          Thêm nhà hàng
        </Button>
      </div>

      <Card>
        <RestaurantList onEdit={handleEdit} onView={handleView} />
      </Card>

      <RestaurantForm
        open={isModalOpen}
        onCancel={handleCancel}
        initialData={editingRestaurant}
      />
    </div>
  )
}
