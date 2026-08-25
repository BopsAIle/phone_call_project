import React, { useState } from 'react'
import { Table, Button, Space, Tag, message, Popconfirm, Select, Row, Col } from 'antd'
import { DeleteOutlined, EditOutlined } from '@ant-design/icons'
import { useBranches, useDeleteBranch } from '../../hooks'
import { LoadingSpinner } from '../../components'
import { BRANCH_STATUS_LABELS } from '../../utils/constants'
import { Branch, BranchStatus } from '../../types'

interface BranchListProps {
  onEdit?: (branch: Branch) => void
  restaurantId?: string
}

export const BranchList: React.FC<BranchListProps> = ({ onEdit, restaurantId }) => {
  const [statusFilter, setStatusFilter] = useState<BranchStatus | undefined>()
  const { data: branches, isLoading } = useBranches(statusFilter, restaurantId)
  const deleteBranch = useDeleteBranch()

  const handleDelete = async (id: string) => {
    try {
      await deleteBranch.mutateAsync(id)
      message.success('Xóa chi nhánh thành công')
    } catch {
      message.error('Xóa chi nhánh thất bại')
    }
  }

  const columns = [
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
      width: 120,
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
    {
      title: 'Hành động',
      key: 'action',
      width: 150,
      render: (_: any, record: Branch) => (
        <Space size="small">
          {onEdit && (
            <Button
              type="primary"
              size="small"
              icon={<EditOutlined />}
              onClick={() => onEdit(record)}
            />
          )}
          <Popconfirm
            title="Xóa chi nhánh"
            description="Bạn chắc chắn muốn xóa chi nhánh này?"
            onConfirm={() => handleDelete(record.id)}
            okText="Xóa"
            cancelText="Hủy"
          >
            <Button
              type="primary"
              danger
              size="small"
              icon={<DeleteOutlined />}
              loading={deleteBranch.isPending}
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
      {!restaurantId && (
        <Row gutter={[16, 16]} style={{ marginBottom: '16px' }}>
          <Col xs={24} sm={12} md={6}>
            <Select
              placeholder="Lọc theo trạng thái"
              allowClear
              onChange={setStatusFilter}
              value={statusFilter}
              style={{ width: '100%' }}
              options={[
                { label: 'Đang hoạt động', value: BranchStatus.ACTIVE },
                { label: 'Không hoạt động', value: BranchStatus.INACTIVE },
                { label: 'Bảo trì', value: BranchStatus.MAINTENANCE },
              ]}
            />
          </Col>
        </Row>
      )}

      <Table
        columns={columns}
        dataSource={branches}
        rowKey="id"
        pagination={{ pageSize: 10 }}
        scroll={{ x: 1200 }}
      />
    </div>
  )
}
