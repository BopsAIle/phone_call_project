import React, { useState } from 'react'
import { Table, Button, Space, Tag, message, Popconfirm, Select, Row, Col } from 'antd'
import { DeleteOutlined, EditOutlined } from '@ant-design/icons'
import { useBookings, useDeleteBooking } from '../../hooks'
import { LoadingSpinner } from '../../components'
import { BOOKING_STATUS_LABELS, BOOKING_SOURCE_LABELS } from '../../utils/constants'
import { Booking, BookingStatus, BookingSource } from '../../types'

interface BookingListProps {
  onEdit?: (booking: Booking) => void
}

export const BookingList: React.FC<BookingListProps> = ({ onEdit }) => {
  const [statusFilter, setStatusFilter] = useState<BookingStatus | undefined>()
  const [sourceFilter, setSourceFilter] = useState<BookingSource | undefined>()

  const { data: bookings, isLoading } = useBookings(statusFilter, sourceFilter)
  const deleteBooking = useDeleteBooking()

  const handleDelete = async (id: string) => {
    try {
      await deleteBooking.mutateAsync(id)
      message.success('Xóa đặt bàn thành công')
    } catch {
      message.error('Xóa đặt bàn thất bại')
    }
  }

  const columns = [
    {
      title: 'Nhà hàng',
      dataIndex: ['restaurant', 'name'],
      key: 'restaurant_name',
      width: 150,
    },
    {
      title: 'Chi nhánh',
      dataIndex: ['branch', 'name'],
      key: 'branch_name',
      width: 180,
    },
    {
      title: 'Tên khách hàng',
      dataIndex: 'customer_name',
      key: 'customer_name',
      width: 150,
    },
    {
      title: 'Số điện thoại',
      dataIndex: 'phone_number',
      key: 'phone_number',
      width: 130,
    },
    {
      title: 'Số người',
      dataIndex: 'party_size',
      key: 'party_size',
      width: 80,
    },
    {
      title: 'Ngày đặt',
      dataIndex: 'booking_date',
      key: 'booking_date',
      width: 110,
      render: (date: string) => new Date(date).toLocaleDateString('vi-VN'),
    },
    {
      title: 'Giờ đặt',
      dataIndex: 'booking_time',
      key: 'booking_time',
      width: 80,
    },
    {
      title: 'Nguồn đặt',
      dataIndex: 'source',
      key: 'source',
      width: 120,
      render: (source: string) => (
        <Tag>
          {BOOKING_SOURCE_LABELS[source as keyof typeof BOOKING_SOURCE_LABELS]}
        </Tag>
      ),
    },
    {
      title: 'Trạng thái',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (status: string) => {
        const colors: Record<string, string> = {
          pending: 'orange',
          confirmed: 'green',
          completed: 'blue',
          cancelled: 'red',
          no_show: 'grey',
        }
        return (
          <Tag color={colors[status]}>
            {BOOKING_STATUS_LABELS[status as keyof typeof BOOKING_STATUS_LABELS]}
          </Tag>
        )
      },
    },
    {
      title: 'Ghi chú',
      dataIndex: 'note',
      key: 'note',
      width: 150,
      ellipsis: true,
    },
    {
      title: 'Hành động',
      key: 'action',
      width: 120,
      fixed: 'right' as const,
      render: (_: any, record: Booking) => (
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
            title="Xóa đặt bàn"
            description="Bạn chắc chắn muốn xóa đặt bàn này?"
            onConfirm={() => handleDelete(record.id)}
            okText="Xóa"
            cancelText="Hủy"
          >
            <Button
              type="primary"
              danger
              size="small"
              icon={<DeleteOutlined />}
              loading={deleteBooking.isPending}
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
      <Row gutter={[16, 16]} style={{ marginBottom: '16px' }}>
        <Col xs={24} sm={12} md={8}>
          <Select
            placeholder="Lọc theo trạng thái"
            allowClear
            onChange={setStatusFilter}
            value={statusFilter}
            style={{ width: '100%' }}
            options={[
              { label: 'Chờ xác nhận', value: BookingStatus.PENDING },
              { label: 'Đã xác nhận', value: BookingStatus.CONFIRMED },
              { label: 'Hoàn thành', value: BookingStatus.COMPLETED },
              { label: 'Hủy bỏ', value: BookingStatus.CANCELLED },
              { label: 'Không xuất hiện', value: BookingStatus.NO_SHOW },
            ]}
          />
        </Col>

        <Col xs={24} sm={12} md={8}>
          <Select
            placeholder="Lọc theo nguồn"
            allowClear
            onChange={setSourceFilter}
            value={sourceFilter}
            style={{ width: '100%' }}
            options={[
              { label: 'Website', value: BookingSource.WEBSITE },
              { label: 'AI Voice', value: BookingSource.PHONE_AI },
              { label: 'Điện thoại', value: BookingSource.PHONE_HUMAN },
              { label: 'Ghé quán', value: BookingSource.WALK_IN },
              { label: 'App', value: BookingSource.APP },
              { label: 'Mạng xã hội', value: BookingSource.SOCIAL_MEDIA },
            ]}
          />
        </Col>
      </Row>

      <Table
        columns={columns}
        dataSource={bookings}
        rowKey="id"
        pagination={{ pageSize: 10 }}
        scroll={{ x: 1800 }}
      />
    </div>
  )
}
