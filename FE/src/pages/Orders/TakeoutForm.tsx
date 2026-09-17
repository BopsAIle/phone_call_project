import React, { useState, useEffect } from 'react'
import {
  Modal,
  Form,
  Input,
  Select,
  DatePicker,
  TimePicker,
  message,
  Space,
  Button,
  Table,
  Divider,
  InputNumber,
  Spin,
  Card,
  Row,
  Col,
} from 'antd'
import { DeleteOutlined } from '@ant-design/icons'
import {
  useCreateTakeoutBooking,
  useMenuItemsByBranch,
  useRestaurants,
  useBranches,
} from '../../hooks'
import { formatPrice } from '../../utils/formatPrice'
import { OrderItemInput, MenuItem } from '../../types'

interface TakeoutFormProps {
  open: boolean
  onCancel: () => void
  onSuccess?: () => void
}

export const TakeoutForm: React.FC<TakeoutFormProps> = ({ open, onCancel, onSuccess }) => {
  const [form] = Form.useForm()
  const [orderItems, setOrderItems] = useState<(OrderItemInput & { menu_item?: MenuItem })[]>([])
  const [selectedMenuItem, setSelectedMenuItem] = useState<string | undefined>()
  const [quantity, setQuantity] = useState(1)
  const restaurantId = Form.useWatch('restaurant_id', form)
  const branchId = Form.useWatch('branch_id', form)

  const createTakeoutBooking = useCreateTakeoutBooking()
  const { data: restaurants } = useRestaurants()
  const { data: branches } = useBranches(undefined, restaurantId)
  const { data: menuItems = [], isLoading: menuLoading } = useMenuItemsByBranch(branchId || '')

  useEffect(() => {
    if (open) {
      form.resetFields()
      setOrderItems([])
      setSelectedMenuItem(undefined)
      setQuantity(1)
    }
  }, [open, form])

  // Watch for branch changes to refetch menu items
  useEffect(() => {
    if (branchId) {
      setOrderItems([])
      setSelectedMenuItem(undefined)
      setQuantity(1)
    }
  }, [branchId])

  const handleAddItem = () => {
    if (!selectedMenuItem) {
      message.error('Vui lòng chọn menu item')
      return
    }

    const menuItem = menuItems.find((m) => m.id === selectedMenuItem)
    if (!menuItem) return

    if (menuItem.quantity_available < quantity) {
      message.error(`Chỉ còn ${menuItem.quantity_available} phần của ${menuItem.name}`)
      return
    }

    const existingItem = orderItems.find((item) => item.menu_item_id === selectedMenuItem)
    if (existingItem) {
      if (existingItem.quantity + quantity > menuItem.quantity_available) {
        message.error(`Chỉ còn ${menuItem.quantity_available} phần của ${menuItem.name}`)
        return
      }
      setOrderItems(
        orderItems.map((item) =>
          item.menu_item_id === selectedMenuItem
            ? { ...item, quantity: item.quantity + quantity }
            : item
        )
      )
    } else {
      setOrderItems([
        ...orderItems,
        {
          menu_item_id: selectedMenuItem,
          quantity,
          menu_item: menuItem,
        },
      ])
    }

    setSelectedMenuItem(undefined)
    setQuantity(1)
  }

  const handleRemoveItem = (menuItemId: string) => {
    setOrderItems(orderItems.filter((item) => item.menu_item_id !== menuItemId))
  }

  const totalPrice = orderItems.reduce(
    (sum, item) => sum + (item.menu_item?.price || 0) * item.quantity,
    0
  )

  const handleSubmit = async (values: any) => {
    try {
      if (orderItems.length === 0) {
        message.error('Vui lòng thêm ít nhất 1 item')
        return
      }

      if (!values.restaurant_id || !values.branch_id) {
        message.error('Vui lòng chọn nhà hàng và chi nhánh')
        return
      }

      if (!values.booking_date || !values.booking_time) {
        message.error('Vui lòng chọn ngày và giờ lấy đồ')
        return
      }

      const bookingData = {
        restaurant_id: values.restaurant_id,
        branch_id: values.branch_id,
        customer_name: values.customer_name,
        customer_phone: values.customer_phone,
        booking_date: values.booking_date.format('YYYY-MM-DD'),
        booking_time: values.booking_time.format('HH:mm'),
        items: orderItems.map(({ menu_item_id, quantity }) => ({
          menu_item_id,
          quantity,
        })),
        note: values.note || '',
      }

      await createTakeoutBooking.mutateAsync(bookingData as any)
      message.success('Tạo đơn mang về thành công')

      form.resetFields()
      setOrderItems([])
      onCancel()
      if (onSuccess) onSuccess()
    } catch (error: any) {
      console.error('Error creating takeout order:', error)
      const errorMessage = error.response?.data?.message || error.message || 'Có lỗi xảy ra'
      message.error(errorMessage)
    }
  }

  const itemColumns = [
    {
      title: 'Tên món',
      dataIndex: ['menu_item', 'name'],
      key: 'name',
    },
    {
      title: 'Giá',
      dataIndex: ['menu_item', 'price'],
      key: 'price',
      render: (price: number) => formatPrice(price),
    },
    {
      title: 'Số lượng',
      dataIndex: 'quantity',
      key: 'quantity',
    },
    {
      title: 'Thành tiền',
      key: 'total',
      render: (_: any, record: any) =>
        formatPrice((record.menu_item?.price || 0) * record.quantity),
    },
    {
      title: 'Hành động',
      key: 'action',
      render: (_: any, record: any) => (
        <Button
          danger
          size="small"
          icon={<DeleteOutlined />}
          onClick={() => handleRemoveItem(record.menu_item_id)}
        />
      ),
    },
  ]

  return (
    <Modal
      title="Tạo Đơn Mang Về"
      open={open}
      onCancel={() => {
        form.resetFields()
        setOrderItems([])
        onCancel()
      }}
      okText="Đặt hàng"
      cancelText="Hủy"
      onOk={() => form.submit()}
      confirmLoading={createTakeoutBooking.isPending}
      width={900}
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={handleSubmit}
        style={{ marginTop: '16px' }}
      >
        {/* Restaurant & Branch */}
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item
              label="Nhà hàng"
              name="restaurant_id"
              rules={[{ required: true, message: 'Vui lòng chọn nhà hàng' }]}
            >
              <Select
                placeholder="Chọn nhà hàng"
                onChange={() => form.setFieldValue('branch_id', undefined)}
                options={restaurants?.map((r) => ({
                  label: r.name,
                  value: r.id,
                }))}
              />
            </Form.Item>
          </Col>
          <Col span={12}>
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
          </Col>
        </Row>

        {/* Customer Info */}
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item
              label="Tên khách hàng"
              name="customer_name"
              rules={[
                { required: true, message: 'Vui lòng nhập tên khách hàng' },
                { min: 1, max: 255, message: 'Tên phải từ 1-255 ký tự' },
              ]}
            >
              <Input placeholder="Nhập tên khách hàng" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              label="Số điện thoại"
              name="customer_phone"
              rules={[
                { required: true, message: 'Vui lòng nhập số điện thoại' },
                { pattern: /^[0-9]{10,20}$/, message: 'Số điện thoại phải từ 10-20 chữ số' },
              ]}
            >
              <Input placeholder="Nhập số điện thoại" />
            </Form.Item>
          </Col>
        </Row>

        {/* Date & Time */}
        <Row gutter={16}>
          <Col span={12}>
            <Form.Item
              label="Ngày lấy đồ"
              name="booking_date"
              rules={[{ required: true, message: 'Vui lòng chọn ngày lấy đồ' }]}
            >
              <DatePicker
                style={{ width: '100%' }}
                placeholder="Chọn ngày lấy đồ"
                disabledDate={(current) => {
                  if (!current) return false
                  const today = new Date()
                  today.setHours(0, 0, 0, 0)
                  const date = current.toDate()
                  date.setHours(0, 0, 0, 0)
                  const maxDate = new Date()
                  maxDate.setMonth(maxDate.getMonth() + 3)
                  maxDate.setHours(0, 0, 0, 0)
                  return date < today || date > maxDate
                }}
              />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              label="Giờ lấy đồ"
              name="booking_time"
              rules={[{ required: true, message: 'Vui lòng chọn giờ lấy đồ' }]}
            >
              <TimePicker
                format="HH:mm"
                style={{ width: '100%' }}
                placeholder="Chọn giờ (HH:mm)"
              />
            </Form.Item>
          </Col>
        </Row>

        {/* Notes */}
        <Form.Item label="Ghi chú (tùy chọn)" name="note">
          <Input.TextArea placeholder="Nhập ghi chú đặc biệt" rows={2} />
        </Form.Item>

        <Divider>Chọn Menu Items</Divider>

        {/* Menu Selection */}
        <Spin spinning={menuLoading}>
          <Space style={{ width: '100%', marginBottom: 16 }} direction="vertical" size="large">
            <Space.Compact style={{ width: '100%' }}>
              <Select
                placeholder="Chọn menu item"
                style={{ flex: 1 }}
                value={selectedMenuItem}
                onChange={setSelectedMenuItem}
                options={menuItems.map((m) => ({
                  label: `${m.name} (${formatPrice(m.price)}) - Còn: ${m.quantity_available}`,
                  value: m.id,
                  disabled: m.quantity_available === 0,
                }))}
              />
              <InputNumber
                min={1}
                max={99}
                value={quantity}
                onChange={(val) => setQuantity(val || 1)}
                placeholder="SL"
                style={{ width: 80 }}
              />
              <Button type="primary" onClick={handleAddItem}>
                Thêm
              </Button>
            </Space.Compact>

            {orderItems.length > 0 && (
              <>
                <Table
                  columns={itemColumns}
                  dataSource={orderItems}
                  rowKey="menu_item_id"
                  pagination={false}
                  size="small"
                />
                <Card style={{ background: '#f5f5f5' }}>
                  <Row justify="end" gutter={16}>
                    <Col>
                      <span>Tổng cộng: </span>
                      <strong style={{ fontSize: 18, color: '#1890ff' }}>
                        {formatPrice(totalPrice)}
                      </strong>
                    </Col>
                  </Row>
                </Card>
              </>
            )}
          </Space>
        </Spin>
      </Form>
    </Modal>
  )
}
