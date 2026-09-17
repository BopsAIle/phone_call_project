import React, { useState } from 'react'
import { Table, Button, Space, Tag, message, Popconfirm, Select, Row, Col } from 'antd'
import { DeleteOutlined, EditOutlined, EyeOutlined } from '@ant-design/icons'
import { useRestaurants, useDeleteRestaurant } from '../../hooks'
import { LoadingSpinner } from '../../components'
import { RESTAURANT_STATUS_LABELS } from '../../utils/constants'
import { Restaurant, RestaurantStatus } from '../../types'

interface RestaurantListProps {
  onEdit?: (restaurant: Restaurant) => void
  onView?: (restaurant: Restaurant) => void
}

export const RestaurantList: React.FC<RestaurantListProps> = ({ onEdit, onView }) => {
  const [statusFilter, setStatusFilter] = useState<RestaurantStatus | undefined>()
  const { data: restaurants, isLoading } = useRestaurants(statusFilter)
  const deleteRestaurant = useDeleteRestaurant()

  const handleDelete = async (id: string) => {
    try {
      await deleteRestaurant.mutateAsync(id)
      message.success('Xóa nhà hàng thành công')
    } catch {
      message.error('Xóa nhà hàng thất bại')
    }
  }

  const columns = [
    {
      title: 'Tên nhà hàng',
      dataIndex: 'name',
      key: 'name',
      width: 250,
    },
    {
      title: 'Hotline',
      dataIndex: 'phone',
      key: 'phone',
      width: 150,
    },
    {
      title: 'Trạng thái',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (status: string) => {
        const colors = {
          active: 'green',
          inactive: 'red',
        }
        return (
          <Tag color={colors[status as keyof typeof colors]}>
            {RESTAURANT_STATUS_LABELS[status as keyof typeof RESTAURANT_STATUS_LABELS]}
          </Tag>
        )
      },
    },
    {
      title: 'Ngày tạo',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 150,
      render: (date: string) => new Date(date).toLocaleDateString('vi-VN'),
    },
    {
      title: 'Hành động',
      key: 'action',
      width: 150,
      render: (_: any, record: Restaurant) => (
        <Space size="small">
          {onView && (
            <Button
              type="default"
              size="small"
              icon={<EyeOutlined />}
              onClick={() => onView(record)}
              title="Xem chi tiết"
            />
          )}
          {onEdit && (
            <Button
              type="primary"
              size="small"
              icon={<EditOutlined />}
              onClick={() => onEdit(record)}
              title="Chỉnh sửa"
            />
          )}
          <Popconfirm
            title="Xóa nhà hàng"
            description="Bạn chắc chắn muốn xóa nhà hàng này?"
            onConfirm={() => handleDelete(record.id)}
            okText="Xóa"
            cancelText="Hủy"
          >
            <Button
              type="primary"
              danger
              size="small"
              icon={<DeleteOutlined />}
              loading={deleteRestaurant.isPending}
              title="Xóa"
            />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  if (isLoading) {
    return <LoadingSpinner />
  }

  return (
    <div>
      <Row gutter={[16, 16]} style={{ marginBottom: '16px' }}>
        <Col xs={24} sm={12} md={6}>
          <Select
            placeholder="Lọc theo trạng thái"
            allowClear
            onChange={setStatusFilter}
            value={statusFilter}
            style={{ width: '100%' }}
            options={[
              { label: 'Đang hoạt động', value: RestaurantStatus.ACTIVE },
              { label: 'Không hoạt động', value: RestaurantStatus.INACTIVE },
            ]}
          />
        </Col>
      </Row>

      <Table
        columns={columns}
        dataSource={restaurants}
        rowKey="id"
        pagination={{ pageSize: 10 }}
        scroll={{ x: 800 }}
      />
    </div>
  )
}
