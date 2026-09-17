import React, { useState } from 'react'
import { Card, Button, Space, Tag, Table, Modal, message, Tabs, Spin, Empty } from 'antd'
import { CheckOutlined, EyeOutlined } from '@ant-design/icons'
import { useBookings, useConfirmTakeoutBooking, useConfirmDeliveryBooking } from '../../hooks'
import { BookingType, BookingStatus, ShipperStatus, OrderItem } from '../../types'
import { formatPrice } from '../../utils/formatPrice'
import { menuApi } from '../../api'
import dayjs from 'dayjs'

interface BookingWithItems {
  id: string
  order_code?: string
  restaurant_id: string
  branch_id: string
  customer_name: string
  phone_number: string
  booking_date: string
  booking_time: string
  booking_type: BookingType
  total_price: number
  status: BookingStatus
  note?: string
  source?: string
  delivery_address?: string
  delivery_phone?: string
  estimated_delivery_time?: string
  actual_delivery_time?: string
  delivery_fee?: number
  shipper_status?: ShipperStatus
  restaurant?: {
    id: string
    name: string
    phone: string
    status: string
    created_at: string
    updated_at: string
  }
  branch?: {
    id: string
    restaurant_id: string
    name: string
    address: string
    phone: string
    opening_time: string
    closing_time: string
    status: string
    created_at: string
    updated_at: string
  }
  order_items?: OrderItem[]
}

interface OrderListProps {
  bookingType?: BookingType
}

export const OrderList: React.FC<OrderListProps> = ({ bookingType: filterBookingType }) => {
  const [detailModal, setDetailModal] = useState<{
    open: boolean
    booking?: BookingWithItems
    loading?: boolean
  }>({
    open: false,
  })

  const { data: allBookings = [], isLoading } = useBookings()
  const confirmTakeout = useConfirmTakeoutBooking()
  const confirmDelivery = useConfirmDeliveryBooking()

  const bookings = (allBookings || []).filter((b: any) => 
    b.booking_type === BookingType.TAKEOUT || b.booking_type === BookingType.DELIVERY
  ) as BookingWithItems[]

  const handleConfirm = (booking: BookingWithItems) => {
    Modal.confirm({
      title: 'Xác nhận đơn hàng',
      content: `Bạn có chắc chắn muốn xác nhận đơn hàng từ ${booking.customer_name}?`,
      okText: 'Xác nhận',
      cancelText: 'Hủy',
      onOk: async () => {
        try {
          if (booking.booking_type === BookingType.TAKEOUT) {
            await confirmTakeout.mutateAsync(booking.id)
          } else {
            await confirmDelivery.mutateAsync(booking.id)
          }
          message.success('Xác nhận đơn hàng thành công')
        } catch (error: any) {
          message.error(error.response?.data?.message || 'Lỗi khi xác nhận')
        }
      },
    })
  }

  const handleShowDetail = async (booking: BookingWithItems) => {
    setDetailModal({ open: true, booking, loading: true })
    try {
      const orderItems = await menuApi.getOrderItems(booking.id)
      setDetailModal({ open: true, booking: { ...booking, order_items: orderItems }, loading: false })
    } catch (error: any) {
      message.error('Lỗi khi tải chi tiết đơn hàng')
      setDetailModal({ open: true, booking, loading: false })
    }
  }

  const statusColors: Record<BookingStatus, string> = {
    [BookingStatus.PENDING]: 'orange',
    [BookingStatus.CONFIRMED]: 'blue',
    [BookingStatus.COMPLETED]: 'green',
    [BookingStatus.CANCELLED]: 'red',
    [BookingStatus.NO_SHOW]: 'gray',
  }

  const statusLabels: Record<BookingStatus, string> = {
    [BookingStatus.PENDING]: 'Chờ xác nhận',
    [BookingStatus.CONFIRMED]: 'Đã xác nhận',
    [BookingStatus.COMPLETED]: 'Hoàn thành',
    [BookingStatus.CANCELLED]: 'Hủy bỏ',
    [BookingStatus.NO_SHOW]: 'Không xuất hiện',
  }

  const shipperStatusColors: Record<ShipperStatus, string> = {
    [ShipperStatus.PENDING]: 'orange',
    [ShipperStatus.ASSIGNED]: 'blue',
    [ShipperStatus.PICKED_UP]: 'cyan',
    [ShipperStatus.ON_THE_WAY]: 'purple',
    [ShipperStatus.DELIVERED]: 'green',
    [ShipperStatus.CANCELLED]: 'red',
  }

  const shipperStatusLabels: Record<ShipperStatus, string> = {
    [ShipperStatus.PENDING]: 'Chờ gán shipper',
    [ShipperStatus.ASSIGNED]: 'Đã gán shipper',
    [ShipperStatus.PICKED_UP]: 'Đã lấy hàng',
    [ShipperStatus.ON_THE_WAY]: 'Đang giao',
    [ShipperStatus.DELIVERED]: 'Đã giao',
    [ShipperStatus.CANCELLED]: 'Hủy',
  }

  const getSourceLabel = (source?: string) => {
    if (!source) return 'N/A'
    switch (source) {
      case 'phone_ai':
        return 'Gọi AI'
      case 'phone_human':
        return 'Gọi nhân viên'
      case 'website':
        return 'Website'
      case 'walk_in':
        return 'Trực tiếp'
      case 'app':
        return 'Ứng dụng'
      case 'social_media':
        return 'Mạng xã hội'
      case 'third_party':
        return 'Bên thứ ba'
      default:
        return source.toUpperCase()
    }
  }

  const columns = [
    {
      title: 'Mã đơn',
      dataIndex: 'order_code',
      key: 'order_code',
      width: 140,
    },
    {
      title: 'Tên khách',
      dataIndex: 'customer_name',
      key: 'customer_name',
    },
    {
      title: 'Số điện thoại',
      dataIndex: 'phone_number',
      key: 'phone_number',
    },
    {
      title: 'Ngày đặt',
      dataIndex: 'booking_date',
      key: 'booking_date',
      render: (date: string) => dayjs(date).format('DD/MM/YYYY'),
    },
    {
      title: 'Giờ đặt',
      dataIndex: 'booking_time',
      key: 'booking_time',
    },
    {
      title: 'Tổng tiền',
      dataIndex: 'total_price',
      key: 'total_price',
      render: (price: number) => formatPrice(price),
    },
    {
      title: 'Trạng thái',
      dataIndex: 'status',
      key: 'status',
      render: (status: BookingStatus) => (
        <Tag color={statusColors[status]}>{statusLabels[status]}</Tag>
      ),
    },
    {
      title: 'Hành động',
      key: 'action',
      render: (_: any, record: BookingWithItems) => (
        <Space size="small">
          <Button
            type="primary"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => handleShowDetail(record)}
          />
          {record.status === BookingStatus.PENDING && (
            <Button
              type="primary"
              size="small"
              icon={<CheckOutlined />}
              onClick={() => handleConfirm(record)}
            />
          )}
        </Space>
      ),
    },
  ]

  const detailColumns = [
    { title: 'Tên món', dataIndex: ['menu_item', 'name'] },
    { title: 'Số lượng', dataIndex: 'quantity' },
    {
      title: 'Giá',
      dataIndex: ['menu_item', 'price'],
      render: (price: number) => formatPrice(price),
    },
    {
      title: 'Thành tiền',
      render: (_: any, record: OrderItem) =>
        formatPrice(record.quantity * (record.menu_item?.price || 0)),
    },
  ]

  const takeoutBookings = bookings.filter((b: any) => b.booking_type === BookingType.TAKEOUT)
  const deliveryBookings = bookings.filter((b: any) => b.booking_type === BookingType.DELIVERY)

  const renderDetailModal = () => (
    <Modal
      title="Chi tiết đơn hàng"
      open={detailModal.open}
      onCancel={() => setDetailModal({ open: false })}
      footer={null}
      width={900}
    >
      {detailModal.booking && (
        <div>
          <Spin spinning={detailModal.loading}>
            <div style={{ marginBottom: 24 }}>
              {/* Thông tin mã đơn và nhà hàng */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
                <div>
                  <p style={{ marginBottom: 8 }}>
                    <strong>Mã đơn:</strong> <Tag color="blue">{detailModal.booking.order_code || 'N/A'}</Tag>
                  </p>
                  <p style={{ marginBottom: 8 }}>
                    <strong>Nhà hàng:</strong> {detailModal.booking.restaurant?.name || 'N/A'}
                  </p>
                  <p style={{ marginBottom: 8 }}>
                    <strong>Chi nhánh:</strong> {detailModal.booking.branch?.name || 'N/A'}
                  </p>
                  <p style={{ marginBottom: 8 }}>
                    <strong>Địa chỉ chi nhánh:</strong> {detailModal.booking.branch?.address || 'N/A'}
                  </p>
                </div>
                <div>
                  <p style={{ marginBottom: 8 }}>
                    <strong>Khách hàng:</strong> {detailModal.booking.customer_name}
                  </p>
                  <p style={{ marginBottom: 8 }}>
                    <strong>Số điện thoại:</strong> {detailModal.booking.phone_number}
                  </p>
                  <p style={{ marginBottom: 8 }}>
                    <strong>Nguồn đặt:</strong> {getSourceLabel(detailModal.booking.source)}
                  </p>
                  <p style={{ marginBottom: 8 }}>
                    <strong>Ghi chú:</strong> {detailModal.booking.note || 'Không có'}
                  </p>
                </div>
              </div>

              {/* Thông tin ngày giờ đặt */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
                <div>
                  <p style={{ marginBottom: 8 }}>
                    <strong>Ngày đặt:</strong> {dayjs(detailModal.booking.booking_date).format('DD/MM/YYYY')}
                  </p>
                  <p style={{ marginBottom: 8 }}>
                    <strong>Giờ đặt:</strong> {detailModal.booking.booking_time}
                  </p>
                </div>
                <div>
                  <p style={{ marginBottom: 8 }}>
                    <strong>Trạng thái:</strong>{' '}
                    <Tag color={statusColors[detailModal.booking.status]}>
                      {statusLabels[detailModal.booking.status]}
                    </Tag>
                  </p>
                </div>
              </div>

              {/* Thông tin giao hàng */}
              {detailModal.booking.booking_type === BookingType.DELIVERY && (
                <div style={{ backgroundColor: '#f5f5f5', padding: 12, borderRadius: 4, marginBottom: 16 }}>
                  <h4 style={{ marginBottom: 12 }}>Thông tin giao hàng</h4>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                    <div>
                      <p style={{ marginBottom: 8 }}>
                        <strong>Địa chỉ giao:</strong> {detailModal.booking.delivery_address || 'N/A'}
                      </p>
                      <p style={{ marginBottom: 8 }}>
                        <strong>SĐT giao:</strong> {detailModal.booking.delivery_phone || 'N/A'}
                      </p>
                    </div>
                    <div>
                      <p style={{ marginBottom: 8 }}>
                        <strong>Thời gian dự kiến:</strong> {detailModal.booking.estimated_delivery_time || 'N/A'}
                      </p>
                      <p style={{ marginBottom: 8 }}>
                        <strong>Thời gian thực tế:</strong> {detailModal.booking.actual_delivery_time ? dayjs(detailModal.booking.actual_delivery_time).format('HH:mm:ss') : 'Chưa giao'}
                      </p>
                    </div>
                  </div>
                  <div style={{ marginTop: 12 }}>
                    <p style={{ marginBottom: 4 }}>
                      <strong>Trạng thái shipper:</strong>{' '}
                      <Tag color={shipperStatusColors[detailModal.booking.shipper_status || ShipperStatus.PENDING]}>
                        {shipperStatusLabels[detailModal.booking.shipper_status || ShipperStatus.PENDING]}
                      </Tag>
                    </p>
                  </div>
                </div>
              )}
            </div>

            {detailModal.booking.order_items && detailModal.booking.order_items.length > 0 && (
              <Table
                title={() => <h4>Chi tiết sản phẩm</h4>}
                columns={detailColumns}
                dataSource={detailModal.booking.order_items}
                rowKey="id"
                pagination={false}
                size="small"
              />
            )}

            <div style={{ marginTop: 24, backgroundColor: '#f9f9f9', padding: 16, borderRadius: 4 }}>
              {detailModal.booking.booking_type === BookingType.DELIVERY && (
                <>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                    <span style={{ fontSize: 14 }}>Tiền hàng:</span>
                    <strong>{formatPrice(detailModal.booking.total_price && detailModal.booking.delivery_fee ? detailModal.booking.total_price - detailModal.booking.delivery_fee : detailModal.booking.total_price)}</strong>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 14, marginBottom: 12, paddingBottom: 12, borderBottom: '1px solid #e8e8e8' }}>
                    <span>Phí giao hàng:</span>
                    <strong>{formatPrice(detailModal.booking.delivery_fee || 0)}</strong>
                  </div>
                </>
              )}
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 16, fontWeight: 'bold' }}>
                <span>Tổng cộng:</span>
                <span style={{ color: '#1890ff' }}>{formatPrice(detailModal.booking.total_price)}</span>
              </div>
            </div>
          </Spin>
        </div>
      )}
    </Modal>
  )

  if (filterBookingType === BookingType.TAKEOUT) {
    return (
      <>
        <Spin spinning={isLoading}>
          {takeoutBookings.length > 0 ? (
            <Table
              columns={columns}
              dataSource={takeoutBookings}
              rowKey="id"
              pagination={{ pageSize: 10 }}
            />
          ) : (
            <Empty description="Không có đơn mang về" />
          )}
        </Spin>
        {renderDetailModal()}
      </>
    )
  }

  if (filterBookingType === BookingType.DELIVERY) {
    return (
      <>
        <Spin spinning={isLoading}>
          {deliveryBookings.length > 0 ? (
            <Table
              columns={[
                ...columns,
                {
                  title: 'Trạng thái Shipper',
                  dataIndex: 'shipper_status',
                  key: 'shipper_status',
                  render: (status: ShipperStatus) => (
                    <Tag color={shipperStatusColors[status]}>
                      {shipperStatusLabels[status]}
                    </Tag>
                  ),
                },
              ]}
              dataSource={deliveryBookings}
              rowKey="id"
              pagination={{ pageSize: 10 }}
            />
          ) : (
            <Empty description="Không có đơn giao hàng" />
          )}
        </Spin>
        {renderDetailModal()}
      </>
    )
  }

  return (
    <>
      <Card title="Quản lý Đơn Hàng">
        <Spin spinning={isLoading}>
          <Tabs
            items={[
              {
                key: 'takeout',
                label: 'Mang Về',
                children: takeoutBookings.length > 0 ? (
                  <Table
                    columns={columns}
                    dataSource={takeoutBookings}
                    rowKey="id"
                    pagination={{ pageSize: 10 }}
                  />
                ) : (
                  <Empty description="Không có đơn mang về" />
                ),
              },
              {
                key: 'delivery',
                label: 'Giao Hàng',
                children: deliveryBookings.length > 0 ? (
                  <Table
                    columns={[
                      ...columns,
                      {
                        title: 'Trạng thái Shipper',
                        dataIndex: 'shipper_status',
                        key: 'shipper_status',
                        render: (status: ShipperStatus) => (
                          <Tag color={shipperStatusColors[status]}>
                            {shipperStatusLabels[status]}
                          </Tag>
                        ),
                      },
                    ]}
                    dataSource={deliveryBookings}
                    rowKey="id"
                    pagination={{ pageSize: 10 }}
                  />
                ) : (
                  <Empty description="Không có đơn giao hàng" />
                ),
              },
            ]}
          />
        </Spin>
      </Card>

      {renderDetailModal()}
    </>
  )
}
