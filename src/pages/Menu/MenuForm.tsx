import React, { useEffect } from 'react'
import { Modal, Form, Input, InputNumber, Select, message } from 'antd'
import {
  useCreateMenuItem,
  useUpdateMenuItem,
} from '../../hooks'
import { MenuItem, MenuItemStatus } from '../../types'

interface MenuFormProps {
  open: boolean
  onCancel: () => void
  onSuccess?: () => void
  initialData?: MenuItem | null
  branchId: string
}

export const MenuForm: React.FC<MenuFormProps> = ({
  open,
  onCancel,
  onSuccess,
  initialData,
  branchId,
}) => {
  const [form] = Form.useForm()
  const createMenuItem = useCreateMenuItem()
  const updateMenuItem = useUpdateMenuItem()

  const isEditing = !!initialData

  useEffect(() => {
    if (initialData) {
      form.setFieldsValue({
        name: initialData.name,
        description: initialData.description,
        price: initialData.price,
        status: initialData.status,
        quantity_available: initialData.quantity_available,
      })
    } else {
      form.resetFields()
    }
  }, [initialData, form, open])

  const handleSubmit = async (values: any) => {
    try {
      if (isEditing && initialData) {
        await updateMenuItem.mutateAsync({
          id: initialData.id,
          data: values,
        })
        message.success('Cập nhật menu item thành công')
      } else {
        await createMenuItem.mutateAsync({
          branch_id: branchId,
          ...values,
        })
        message.success('Tạo menu item thành công')
      }
      onCancel()
      if (onSuccess) onSuccess()
    } catch (error: any) {
      message.error(error.response?.data?.message || 'Có lỗi xảy ra')
    }
  }

  return (
    <Modal
      title={isEditing ? 'Cập nhật Menu Item' : 'Tạo Menu Item Mới'}
      open={open}
      onCancel={onCancel}
      okText={isEditing ? 'Cập nhật' : 'Tạo mới'}
      cancelText="Hủy"
      onOk={() => form.submit()}
      confirmLoading={createMenuItem.isPending || updateMenuItem.isPending}
      width={500}
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={handleSubmit}
        style={{ marginTop: '16px' }}
      >
        <Form.Item
          label="Tên món"
          name="name"
          rules={[
            { required: true, message: 'Vui lòng nhập tên món' },
            { min: 3, message: 'Tên món phải ít nhất 3 ký tự' },
          ]}
        >
          <Input placeholder="Nhập tên món" />
        </Form.Item>

        <Form.Item
          label="Mô tả"
          name="description"
          rules={[{ max: 500, message: 'Mô tả tối đa 500 ký tự' }]}
        >
          <Input.TextArea placeholder="Nhập mô tả (tùy chọn)" rows={3} />
        </Form.Item>

        <Form.Item
          label="Giá"
          name="price"
          rules={[
            { required: true, message: 'Vui lòng nhập giá' },
            { type: 'number', min: 0, message: 'Giá phải >= 0' },
          ]}
        >
          <InputNumber
            placeholder="Nhập giá"
            style={{ width: '100%' }}
            min={0}
            formatter={(value) => `${value}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
          />
        </Form.Item>

        <Form.Item
          label="Số lượng có sẵn"
          name="quantity_available"
          rules={[{ type: 'number', min: 0, message: 'Số lượng phải >= 0' }]}
          initialValue={1000}
        >
          <InputNumber placeholder="Nhập số lượng" style={{ width: '100%' }} min={0} />
        </Form.Item>

        {isEditing && (
          <Form.Item
            label="Trạng thái"
            name="status"
            rules={[{ required: true, message: 'Vui lòng chọn trạng thái' }]}
          >
            <Select
              options={[
                { label: 'Có sẵn', value: MenuItemStatus.AVAILABLE },
                { label: 'Không khả dụng', value: MenuItemStatus.UNAVAILABLE },
                { label: 'Hết hàng', value: MenuItemStatus.SOLD_OUT },
              ]}
            />
          </Form.Item>
        )}
      </Form>
    </Modal>
  )
}
