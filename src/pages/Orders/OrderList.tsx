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
  customer_name: string
  phone_number: string
  booking_date: string
  booking_time: string
  booking_type: BookingType
  total_price: number
  status: BookingStatus
  delivery_address?: string
  estimated_delivery_time?: string
  delivery_fee?: number
  shipper_status?: ShipperStatus
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

  const columns = [
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

  if (filterBookingType === BookingType.TAKEOUT) {
    return (
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
        <Modal
          title="Chi tiết đơn hàng"
          open={detailModal.open}
          onCancel={() => setDetailModal({ open: false })}
          footer={null}
          width={700}
        >
          {detailModal.booking && (
            <div>
              <div style={{ marginBottom: 16 }}>
                <p>
                  <strong>Khách hàng:</strong> {detailModal.booking.customer_name}
                </p>
                <p>
                  <strong>Số điện thoại:</strong> {detailModal.booking.phone_number}
                </p>
                <p>
                  <strong>Ngày đặt:</strong> {dayjs(detailModal.booking.booking_date).format('DD/MM/YYYY')} lúc{' '}
                  {detailModal.booking.booking_time}
                </p>
              </div>

              <Table
                title={() => <h4>Chi tiết đơn hàng</h4>}
                columns={detailColumns}
                dataSource={detailModal.booking.order_items}
                rowKey="id"
                pagination={false}
              />

              <div style={{ marginTop: 16, textAlign: 'right' }}>
                <p style={{ fontSize: 16, fontWeight: 'bold' }}>
                  Tổng cộng: {formatPrice(detailModal.booking.total_price)}
                </p>
              </div>
            </div>
          )}
        </Modal>
      </Spin>
    )
  }

  if (filterBookingType === BookingType.DELIVERY) {
    return (
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
        <Modal
          title="Chi tiết đơn hàng"
          open={detailModal.open}
          onCancel={() => setDetailModal({ open: false })}
          footer={null}
          width={700}
        >
          {detailModal.booking && (
            <div>
              <div style={{ marginBottom: 16 }}>
                <p>
                  <strong>Khách hàng:</strong> {detailModal.booking.customer_name}
                </p>
                <p>
                  <strong>Số điện thoại:</strong> {detailModal.booking.phone_number}
                </p>
                <p>
                  <strong>Ngày đặt:</strong> {dayjs(detailModal.booking.booking_date).format('DD/MM/YYYY')} lúc{' '}
                  {detailModal.booking.booking_time}
                </p>
                {detailModal.booking.booking_type === BookingType.DELIVERY && (
                  <>
                    <p>
                      <strong>Địa chỉ giao:</strong> {detailModal.booking.delivery_address}
                    </p>
                    <p>
                      <strong>Thời gian giao dự kiến:</strong> {detailModal.booking.estimated_delivery_time}
                    </p>
                  </>
                )}
              </div>

              <Table
                title={() => <h4>Chi tiết đơn hàng</h4>}
                columns={detailColumns}
                dataSource={detailModal.booking.order_items}
                rowKey="id"
                pagination={false}
              />

              <div style={{ marginTop: 16, textAlign: 'right' }}>
                {detailModal.booking.booking_type === BookingType.DELIVERY && (
                  <>
                    <p style={{ fontSize: 14 }}>
                      Tiền hàng: <strong>{formatPrice(detailModal.booking.total_price && detailModal.booking.delivery_fee ? detailModal.booking.total_price - detailModal.booking.delivery_fee : detailModal.booking.total_price)}</strong>
                    </p>
                    <p style={{ fontSize: 14 }}>
                      Phí giao hàng: <strong>{formatPrice(detailModal.booking.delivery_fee || 0)}</strong>
                    </p>
                  </>
                )}
                <p style={{ fontSize: 16, fontWeight: 'bold' }}>
                  Tổng cộng: {formatPrice(detailModal.booking.total_price)}
                </p>
              </div>
            </div>
          )}
        </Modal>
      </Spin>
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

      <Modal
        title="Chi tiết đơn hàng"
        open={detailModal.open}
        onCancel={() => setDetailModal({ open: false })}
        footer={null}
        width={700}
      >
        {detailModal.booking && (
          <div>
            <div style={{ marginBottom: 16 }}>
              <p>
                <strong>Khách hàng:</strong> {detailModal.booking.customer_name}
              </p>
              <p>
                <strong>Số điện thoại:</strong> {detailModal.booking.phone_number}
              </p>
              <p>
                <strong>Ngày đặt:</strong> {dayjs(detailModal.booking.booking_date).format('DD/MM/YYYY')} lúc{' '}
                {detailModal.booking.booking_time}
              </p>
              {detailModal.booking.booking_type === BookingType.DELIVERY && (
                <>
                  <p>
                    <strong>Địa chỉ giao:</strong> {detailModal.booking.delivery_address}
                  </p>
                  <p>
                    <strong>Thời gian giao dự kiến:</strong> {detailModal.booking.estimated_delivery_time}
                  </p>
                </>
              )}
            </div>

            <Table
              title={() => <h4>Chi tiết đơn hàng</h4>}
              columns={detailColumns}
              dataSource={detailModal.booking.order_items}
              rowKey="id"
              pagination={false}
            />

            <div style={{ marginTop: 16, textAlign: 'right' }}>
              <Spin spinning={detailModal.loading}>
                {detailModal.booking.booking_type === BookingType.DELIVERY && (
                  <>
                    <p style={{ fontSize: 14 }}>
                      Tiền hàng: <strong>{formatPrice(detailModal.booking.total_price && detailModal.booking.delivery_fee ? detailModal.booking.total_price - detailModal.booking.delivery_fee : detailModal.booking.total_price)}</strong>
                    </p>
                    <p style={{ fontSize: 14 }}>
                      Phí giao hàng: <strong>{formatPrice(detailModal.booking.delivery_fee || 0)}</strong>
                    </p>
                  </>
                )}
                <p style={{ fontSize: 16, fontWeight: 'bold' }}>
                  Tổng cộng: {formatPrice(detailModal.booking.total_price)}
                </p>
              </Spin>
            </div>
          </div>
        )}
      </Modal>
    </>
  )
}
