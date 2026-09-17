import React, { useEffect } from 'react'
import { Modal, Form, Input, Select, TimePicker, message } from 'antd'
import dayjs from 'dayjs'
import { useCreateBranch, useUpdateBranch, useRestaurants } from '../../hooks'
import { Branch, BranchStatus } from '../../types'

interface BranchFormProps {
  open: boolean
  onCancel: () => void
  initialData?: Branch | null
}

export const BranchForm: React.FC<BranchFormProps> = ({
  open,
  onCancel,
  initialData,
}) => {
  const [form] = Form.useForm()
  const createBranch = useCreateBranch()
  const updateBranch = useUpdateBranch()
  const { data: restaurants } = useRestaurants()

  const isEditing = !!initialData

  useEffect(() => {
    if (initialData) {
      form.setFieldsValue({
        restaurant_id: initialData.restaurant_id,
        name: initialData.name,
        phone: initialData.phone,
        address: initialData.address,
        opening_time: initialData.opening_time ? dayjs(initialData.opening_time, 'HH:mm') : null,
        closing_time: initialData.closing_time ? dayjs(initialData.closing_time, 'HH:mm') : null,
        status: initialData.status,
      })
    } else {
      form.resetFields()
    }
  }, [initialData, form, open])

  const handleSubmit = async (values: any) => {
    try {
      const data = {
        ...values,
        opening_time: values.opening_time?.format('HH:mm'),
        closing_time: values.closing_time?.format('HH:mm'),
      }

      if (isEditing && initialData) {
        await updateBranch.mutateAsync({
          id: initialData.id,
          data,
        })
        message.success('Cập nhật chi nhánh thành công')
      } else {
        await createBranch.mutateAsync(data)
        message.success('Tạo chi nhánh thành công')
      }
      onCancel()
    } catch (error: any) {
      message.error(error.response?.data?.message || 'Có lỗi xảy ra')
    }
  }

  return (
    <Modal
      title={isEditing ? 'Cập nhật chi nhánh' : 'Tạo chi nhánh mới'}
      open={open}
      onCancel={onCancel}
      okText={isEditing ? 'Cập nhật' : 'Tạo mới'}
      cancelText="Hủy"
      onOk={() => form.submit()}
      confirmLoading={createBranch.isPending || updateBranch.isPending}
      width={600}
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={handleSubmit}
        style={{ marginTop: '16px' }}
      >
        {!isEditing && (
          <Form.Item
            label="Nhà hàng"
            name="restaurant_id"
            rules={[{ required: true, message: 'Vui lòng chọn nhà hàng' }]}
          >
            <Select
              placeholder="Chọn nhà hàng"
              options={restaurants?.map((r) => ({
                label: r.name,
                value: r.id,
              }))}
            />
          </Form.Item>
        )}

        <Form.Item
          label="Tên chi nhánh"
          name="name"
          rules={[
            { required: true, message: 'Vui lòng nhập tên chi nhánh' },
            { min: 3, message: 'Tên phải ít nhất 3 ký tự' },
          ]}
        >
          <Input placeholder="Nhập tên chi nhánh" />
        </Form.Item>

        <Form.Item
          label="Địa chỉ"
          name="address"
          rules={[
            { required: true, message: 'Vui lòng nhập địa chỉ' },
          ]}
        >
          <Input.TextArea placeholder="Nhập địa chỉ" rows={3} />
        </Form.Item>

        <Form.Item
          label="Số điện thoại"
          name="phone"
          rules={[
            { required: true, message: 'Vui lòng nhập số điện thoại' },
            {
              pattern: /^[0-9]{10,}$/,
              message: 'Số điện thoại không hợp lệ',
            },
          ]}
        >
          <Input placeholder="Nhập số điện thoại" />
        </Form.Item>

        <Form.Item
          label="Giờ mở cửa"
          name="opening_time"
          rules={[{ required: true, message: 'Vui lòng chọn giờ mở cửa' }]}
        >
          <TimePicker format="HH:mm" placeholder="Chọn giờ mở cửa" />
        </Form.Item>

        <Form.Item
          label="Giờ đóng cửa"
          name="closing_time"
          rules={[{ required: true, message: 'Vui lòng chọn giờ đóng cửa' }]}
        >
          <TimePicker format="HH:mm" placeholder="Chọn giờ đóng cửa" />
        </Form.Item>

        {isEditing && (
          <Form.Item
            label="Trạng thái"
            name="status"
            rules={[{ required: true, message: 'Vui lòng chọn trạng thái' }]}
          >
            <Select
              options={[
                { label: 'Đang hoạt động', value: BranchStatus.ACTIVE },
                { label: 'Không hoạt động', value: BranchStatus.INACTIVE },
                { label: 'Bảo trì', value: BranchStatus.MAINTENANCE },
              ]}
            />
          </Form.Item>
        )}
      </Form>
    </Modal>
  )
}
