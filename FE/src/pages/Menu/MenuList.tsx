import React, { useState } from 'react'
import {
  Table,
  Button,
  Space,
  Tag,
  Modal,
  message,
  Spin,
  Empty,
  Card,
  Select,
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import { useMenuItemsByBranch, useDeleteMenuItem } from '../../hooks'
import { MenuItem, MenuItemStatus } from '../../types'
import { formatPrice } from '../../utils/formatPrice'
import { useBranches } from '../../hooks'
import { MenuForm } from './MenuForm'

export const MenuList: React.FC = () => {
  const [selectedBranchId, setSelectedBranchId] = useState<string | undefined>()
  const [editingItem, setEditingItem] = useState<MenuItem | null>(null)
  const [formOpen, setFormOpen] = useState(false)

  const { data: branches } = useBranches()
  const { data: menuItems = [], isLoading } = useMenuItemsByBranch(selectedBranchId || '')
  const deleteMenuItem = useDeleteMenuItem()

  const handleDelete = (id: string) => {
    Modal.confirm({
      title: 'Xác nhận xóa',
      content: 'Bạn có chắc chắn muốn xóa menu item này?',
      okText: 'Xóa',
      cancelText: 'Hủy',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await deleteMenuItem.mutateAsync(id)
          message.success('Xóa menu item thành công')
        } catch (error: any) {
          message.error(error.response?.data?.message || 'Lỗi khi xóa')
        }
      },
    })
  }

  const handleEdit = (item: MenuItem) => {
    setEditingItem(item)
    setFormOpen(true)
  }

  const handleCreate = () => {
    setEditingItem(null)
    setFormOpen(true)
  }

  const handleFormClose = () => {
    setFormOpen(false)
    setEditingItem(null)
  }

  const statusColors: Record<MenuItemStatus, string> = {
    [MenuItemStatus.AVAILABLE]: 'green',
    [MenuItemStatus.UNAVAILABLE]: 'orange',
    [MenuItemStatus.SOLD_OUT]: 'red',
  }

  const statusLabels: Record<MenuItemStatus, string> = {
    [MenuItemStatus.AVAILABLE]: 'Có sẵn',
    [MenuItemStatus.UNAVAILABLE]: 'Không khả dụng',
    [MenuItemStatus.SOLD_OUT]: 'Hết hàng',
  }

  const columns = [
    {
      title: 'Tên món',
      dataIndex: 'name',
      key: 'name',
      width: 200,
    },
    {
      title: 'Mô tả',
      dataIndex: 'description',
      key: 'description',
      width: 250,
      ellipsis: true,
    },
    {
      title: 'Giá',
      dataIndex: 'price',
      key: 'price',
      width: 100,
      render: (price: number) => formatPrice(price),
    },
    {
      title: 'Số lượng',
      dataIndex: 'quantity_available',
      key: 'quantity_available',
      width: 100,
      render: (qty: number) => <strong>{qty}</strong>,
    },
    {
      title: 'Trạng thái',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (status: MenuItemStatus) => (
        <Tag color={statusColors[status]}>{statusLabels[status]}</Tag>
      ),
    },
    {
      title: 'Hành động',
      key: 'actions',
      width: 120,
      render: (_: any, record: MenuItem) => (
        <Space size="small">
          <Button
            type="primary"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
          />
          <Button
            danger
            size="small"
            icon={<DeleteOutlined />}
            onClick={() => handleDelete(record.id)}
          />
        </Space>
      ),
    },
  ]

  return (
    <Card
      title="Quản lý Menu"
      extra={
        <Space>
          <Select
            placeholder="Chọn chi nhánh"
            style={{ width: 250 }}
            allowClear
            onChange={setSelectedBranchId}
            options={branches?.map((b) => ({
              label: b.name,
              value: b.id,
            }))}
          />
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={handleCreate}
            disabled={!selectedBranchId}
          >
            Thêm menu item
          </Button>
        </Space>
      }
    >
      {!selectedBranchId ? (
        <Empty description="Vui lòng chọn chi nhánh" style={{ marginTop: 50 }} />
      ) : (
        <>
          <Spin spinning={isLoading}>
            <Table
              columns={columns}
              dataSource={menuItems}
              rowKey="id"
              pagination={{
                pageSize: 10,
                showSizeChanger: true,
                showTotal: (total) => `Tổng ${total} items`,
              }}
            />
          </Spin>
          <MenuForm
            open={formOpen}
            onCancel={handleFormClose}
            initialData={editingItem}
            branchId={selectedBranchId}
          />
        </>
      )}
    </Card>
  )
}
