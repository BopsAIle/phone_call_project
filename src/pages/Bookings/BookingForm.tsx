import React, { useEffect } from 'react'
import { Modal, Form, Input, Select, DatePicker, TimePicker, message, InputNumber } from 'antd'
import dayjs from 'dayjs'
import { useCreateBooking, useUpdateBooking, useRestaurants, useBranches } from '../../hooks'
import { Booking, BookingStatus } from '../../types'

interface BookingFormProps {
  open: boolean
  onCancel: () => void
  initialData?: Booking | null
}

export const BookingForm: React.FC<BookingFormProps> = ({
  open,
  onCancel,
  initialData,
}) => {
  const [form] = Form.useForm()
  const [selectedRestaurant, setSelectedRestaurant] = React.useState<string | undefined>()

  const createBooking = useCreateBooking()
  const updateBooking = useUpdateBooking()
  const { data: restaurants } = useRestaurants()
  const { data: branches } = useBranches(undefined, selectedRestaurant)

  const isEditing = !!initialData

  useEffect(() => {
    if (initialData) {
      form.setFieldsValue({
        customer_name: initialData.customer_name,
        phone_number: initialData.phone_number,
        party_size: initialData.party_size,
        booking_date: dayjs(initialData.booking_date),
        booking_time: dayjs(initialData.booking_time, 'HH:mm:ss'),
        note: initialData.note,
        status: initialData.status,
      })
      setSelectedRestaurant(initialData.restaurant_id)
    } else {
      form.resetFields()
      setSelectedRestaurant(undefined)
    }
  }, [initialData, form, open])

  const handleSubmit = async (values: any) => {
    try {
      if (isEditing && initialData) {
        // Update - gửi toàn bộ data đã thay đổi
        const updateData: any = {}

        if (values.customer_name && values.customer_name !== initialData.customer_name) {
          updateData.customer_name = values.customer_name
        }
        if (values.phone_number && values.phone_number !== initialData.phone_number) {
          updateData.phone_number = values.phone_number
        }
        if (values.party_size !== undefined && values.party_size !== initialData.party_size) {
          updateData.party_size = values.party_size
        }
        if (values.booking_date) {
          const newDate = values.booking_date.format('YYYY-MM-DD')
          if (newDate !== initialData.booking_date) {
            updateData.booking_date = newDate
          }
        }
        if (values.booking_time) {
          const newTime = values.booking_time.format('HH:mm')
          if (newTime !== initialData.booking_time) {
            updateData.booking_time = newTime
          }
        }
        if (values.note !== undefined && values.note !== initialData.note) {
          updateData.note = values.note
        }
        if (values.status && values.status !== initialData.status) {
          updateData.status = values.status
        }

        // Nếu không có gì thay đổi
        if (Object.keys(updateData).length === 0) {
          message.warning('Không có dữ liệu nào được thay đổi')
          return
        }

        await updateBooking.mutateAsync({
          id: initialData.id,
          data: updateData,
        })
        message.success('Cập nhật đặt bàn thành công')
      } else {
        // Create - bắt buộc chọn nhà hàng + chi nhánh
        if (!selectedRestaurant) {
          message.error('Vui lòng chọn nhà hàng')
          return
        }

        const selectedBranch = form.getFieldValue('branch_id')
        if (!selectedBranch) {
          message.error('Vui lòng chọn chi nhánh')
          return
        }

        const data = {
          restaurant_id: selectedRestaurant,
          branch_id: selectedBranch,
          customer_name: values.customer_name,
          phone_number: values.phone_number,
          party_size: values.party_size,
          booking_date: values.booking_date.format('YYYY-MM-DD'),
          booking_time: values.booking_time.format('HH:mm'),
          note: values.note,
        }

        await createBooking.mutateAsync(data)
        message.success('Tạo đặt bàn thành công')
      }
      onCancel()
    } catch (error: any) {
      message.error(error.response?.data?.message || 'Có lỗi xảy ra')
    }
  }

  return (
    <Modal
      title={isEditing ? 'Cập nhật đặt bàn' : 'Tạo đặt bàn mới'}
      open={open}
      onCancel={onCancel}
      okText={isEditing ? 'Cập nhật' : 'Tạo mới'}
      cancelText="Hủy"
      onOk={() => form.submit()}
      confirmLoading={createBooking.isPending || updateBooking.isPending}
      width={600}
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={handleSubmit}
        style={{ marginTop: '16px' }}
      >
        {!isEditing && (
          <>
            <Form.Item
              label="Nhà hàng"
              rules={[{ required: true, message: 'Vui lòng chọn nhà hàng' }]}
            >
              <Select
                placeholder="Chọn nhà hàng"
                onChange={setSelectedRestaurant}
                options={restaurants?.map((r) => ({
                  label: r.name,
                  value: r.id,
                }))}
              />
            </Form.Item>

            <Form.Item
              label="Chi nhánh"
              name="branch_id"
              rules={[{ required: true, message: 'Vui lòng chọn chi nhánh' }]}
            >
              <Select
                placeholder="Chọn chi nhánh"
                options={branches?.map((b) => ({
                  label: b.name,
                  value: b.id,
                }))}
              />
            </Form.Item>
          </>
        )}

        <Form.Item
          label="Tên khách hàng"
          name="customer_name"
          rules={[{ required: true, message: 'Vui lòng nhập tên khách hàng' }]}
        >
          <Input placeholder="Nhập tên khách hàng" />
        </Form.Item>

        <Form.Item
          label="Số điện thoại"
          name="phone_number"
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
          label="Số người"
          name="party_size"
          rules={[
            { required: true, message: 'Vui lòng nhập số người' },
            { type: 'number', min: 1, message: 'Số người phải >= 1' },
          ]}
        >
          <InputNumber min={1} placeholder="Nhập số người" style={{ width: '100%' }} />
        </Form.Item>

        <Form.Item
          label="Ngày đặt"
          name="booking_date"
          rules={[{ required: true, message: 'Vui lòng chọn ngày đặt' }]}
        >
          <DatePicker placeholder="Chọn ngày đặt" style={{ width: '100%' }} />
        </Form.Item>

        <Form.Item
          label="Giờ đặt"
          name="booking_time"
          rules={[{ required: true, message: 'Vui lòng chọn giờ đặt' }]}
        >
          <TimePicker format="HH:mm" placeholder="Chọn giờ đặt" style={{ width: '100%' }} />
        </Form.Item>

        <Form.Item label="Ghi chú" name="note">
          <Input.TextArea placeholder="Nhập ghi chú" rows={3} />
        </Form.Item>

        {isEditing && (
          <Form.Item
            label="Trạng thái"
            name="status"
            rules={[{ required: true, message: 'Vui lòng chọn trạng thái' }]}
          >
            <Select
              options={[
                { label: 'Chờ xác nhận', value: BookingStatus.PENDING },
                { label: 'Đã xác nhận', value: BookingStatus.CONFIRMED },
                { label: 'Hoàn thành', value: BookingStatus.COMPLETED },
                { label: 'Hủy bỏ', value: BookingStatus.CANCELLED },
                { label: 'Không xuất hiện', value: BookingStatus.NO_SHOW },
              ]}
            />
          </Form.Item>
        )}
      </Form>
    </Modal>
  )
}
