import React, { useEffect } from 'react'
import { Modal, Form, Input, Select, message } from 'antd'
import { useCreateRestaurant, useUpdateRestaurant } from '../../hooks'
import { Restaurant, RestaurantStatus } from '../../types'

interface RestaurantFormProps {
  open: boolean
  onCancel: () => void
  initialData?: Restaurant | null
}

export const RestaurantForm: React.FC<RestaurantFormProps> = ({
  open,
  onCancel,
  initialData,
}) => {
  const [form] = Form.useForm()
  const createRestaurant = useCreateRestaurant()
  const updateRestaurant = useUpdateRestaurant()

  const isEditing = !!initialData

  useEffect(() => {
    if (initialData) {
      form.setFieldsValue({
        name: initialData.name,
        phone: initialData.phone,
        status: initialData.status,
      })
    } else {
      form.resetFields()
    }
  }, [initialData, form, open])

  const handleSubmit = async (values: any) => {
    try {
      if (isEditing && initialData) {
        await updateRestaurant.mutateAsync({
          id: initialData.id,
          data: values,
        })
        message.success('Cập nhật nhà hàng thành công')
      } else {
        await createRestaurant.mutateAsync(values)
        message.success('Tạo nhà hàng thành công')
      }
      onCancel()
    } catch (error: any) {
      message.error(error.response?.data?.message || 'Có lỗi xảy ra')
    }
  }

  return (
    <Modal
      title={isEditing ? 'Cập nhật nhà hàng' : 'Tạo nhà hàng mới'}
      open={open}
      onCancel={onCancel}
      okText={isEditing ? 'Cập nhật' : 'Tạo mới'}
      cancelText="Hủy"
      onOk={() => form.submit()}
      confirmLoading={createRestaurant.isPending || updateRestaurant.isPending}
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={handleSubmit}
        style={{ marginTop: '16px' }}
      >
        <Form.Item
          label="Tên nhà hàng"
          name="name"
          rules={[
            { required: true, message: 'Vui lòng nhập tên nhà hàng' },
            { min: 3, message: 'Tên phải ít nhất 3 ký tự' },
          ]}
        >
          <Input placeholder="Nhập tên nhà hàng" />
        </Form.Item>

        <Form.Item
          label="Số hotline"
          name="phone"
          rules={[
            { required: true, message: 'Vui lòng nhập số hotline' },
            {
              pattern: /^[0-9]{10,}$/,
              message: 'Số điện thoại không hợp lệ',
            },
          ]}
        >
          <Input placeholder="Nhập số hotline" />
        </Form.Item>

        {isEditing && (
          <Form.Item
            label="Trạng thái"
            name="status"
            rules={[{ required: true, message: 'Vui lòng chọn trạng thái' }]}
          >
            <Select
              options={[
                { label: 'Đang hoạt động', value: RestaurantStatus.ACTIVE },
                { label: 'Không hoạt động', value: RestaurantStatus.INACTIVE },
              ]}
            />
          </Form.Item>
        )}
      </Form>
    </Modal>
  )
}
