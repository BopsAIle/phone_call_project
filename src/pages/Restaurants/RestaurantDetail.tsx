import React from 'react'
import { Card, Button, Table, Tag, Descriptions, Empty, Space, Spin } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { useBranchesByRestaurant } from '../../hooks'
import { BRANCH_STATUS_LABELS } from '../../utils/constants'
import { Restaurant, Branch } from '../../types'

interface RestaurantDetailProps {
  restaurant: Restaurant
  onBack: () => void
}

export const RestaurantDetail: React.FC<RestaurantDetailProps> = ({
  restaurant,
  onBack,
}) => {
  const { data: branches, isLoading } = useBranchesByRestaurant(restaurant.id)

  const branchColumns = [
    {
      title: 'Tên chi nhánh',
      dataIndex: 'name',
      key: 'name',
      width: 200,
    },
    {
      title: 'Địa chỉ',
      dataIndex: 'address',
      key: 'address',
      width: 250,
    },
    {
      title: 'Số điện thoại',
      dataIndex: 'phone',
      key: 'phone',
      width: 150,
    },
    {
      title: 'Giờ mở cửa',
      dataIndex: 'opening_time',
      key: 'opening_time',
      width: 120,
    },
    {
      title: 'Giờ đóng cửa',
      dataIndex: 'closing_time',
      key: 'closing_time',
      width: 120,
    },
    {
      title: 'Trạng thái',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => {
        const colors = {
          active: 'green',
          inactive: 'red',
          maintenance: 'orange',
        }
        return (
          <Tag color={colors[status as keyof typeof colors]}>
            {BRANCH_STATUS_LABELS[status as keyof typeof BRANCH_STATUS_LABELS]}
          </Tag>
        )
      },
    },
  ]

  return (
    <div>
      <Button
        icon={<ArrowLeftOutlined />}
        onClick={onBack}
        style={{ marginBottom: '16px' }}
      >
        Quay lại
      </Button>

      <Card title="Thông tin nhà hàng" style={{ marginBottom: '24px' }}>
        <Descriptions column={2} bordered>
          <Descriptions.Item label="Tên nhà hàng">
            {restaurant.name}
          </Descriptions.Item>
          <Descriptions.Item label="Hotline">
            {restaurant.phone}
          </Descriptions.Item>
          <Descriptions.Item label="Trạng thái">
            <Tag color={restaurant.status === 'active' ? 'green' : 'red'}>
              {restaurant.status === 'active' ? 'Đang hoạt động' : 'Không hoạt động'}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Ngày tạo">
            {new Date(restaurant.created_at).toLocaleDateString('vi-VN')}
          </Descriptions.Item>
          <Descriptions.Item label="Cập nhật lần cuối">
            {new Date(restaurant.updated_at).toLocaleDateString('vi-VN')}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="Danh sách chi nhánh">
        <Spin spinning={isLoading}>
          {branches && branches.length > 0 ? (
            <Table
              columns={branchColumns}
              dataSource={branches}
              rowKey="id"
              pagination={{ pageSize: 10 }}
              scroll={{ x: 1200 }}
            />
          ) : (
            <Empty
              description="Không có chi nhánh nào"
              style={{ marginTop: '24px' }}
            />
          )}
        </Spin>
      </Card>
    </div>
  )
}
