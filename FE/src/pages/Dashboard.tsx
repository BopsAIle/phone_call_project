import React from 'react'
import { Row, Col, Card, Statistic, Table, Tag, Empty } from 'antd'
import {
  ShopOutlined,
  CalendarOutlined,
  TeamOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons'
import { useBookingStats, useRestaurants, useBranches, useBookings } from '../hooks'
import { LoadingSpinner } from '../components'
import { BOOKING_STATUS_LABELS } from '../utils/constants'

export const Dashboard: React.FC = () => {
  const { data: stats, isLoading: statsLoading } = useBookingStats()
  const { data: restaurants } = useRestaurants()
  const { data: branches } = useBranches()
  const { data: bookings } = useBookings()

  if (statsLoading) {
    return <LoadingSpinner />
  }

  // Lấy 5 đặt bàn gần đây nhất
  const recentBookings = bookings
    ?.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 5)

  const bookingColumns = [
    {
      title: 'Khách hàng',
      dataIndex: 'customer_name',
      key: 'customer_name',
      width: '20%',
    },
    {
      title: 'Nhà hàng',
      dataIndex: ['restaurant', 'name'],
      key: 'restaurant_name',
      width: '25%',
      ellipsis: true,
    },
    {
      title: 'Ngày đặt',
      dataIndex: 'booking_date',
      key: 'booking_date',
      width: '15%',
      render: (date: string) => new Date(date).toLocaleDateString('vi-VN'),
    },
    {
      title: 'Giờ đặt',
      dataIndex: 'booking_time',
      key: 'booking_time',
      width: '12%',
    },
    {
      title: 'Trạng thái',
      dataIndex: 'status',
      key: 'status',
      width: '28%',
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
  ]

  return (
    <div>
      <div style={{ marginBottom: '32px' }}>
        <h2 style={{ margin: 0, fontSize: '28px', fontWeight: 600, color: '#001529' }}>
          👋 Xin chào, bạn quản lý!
        </h2>
        <p style={{ margin: '8px 0 0 0', color: 'rgba(0, 0, 0, 0.45)', fontSize: '14px' }}>
          Tổng quan chi tiết về các hoạt động của hệ thống
        </p>
      </div>

      {/* Stats Cards */}
      <Row gutter={[16, 16]} style={{ marginBottom: '32px' }}>
        <Col xs={24} sm={12} lg={6}>
          <Card
            hoverable
            style={{
              background: '#f6ede5',
              borderLeft: '4px solid #D4663A',
              border: 'none',
            }}
          >
            <Statistic
              title={<span style={{ color: 'rgba(0, 0, 0, 0.65)' }}>Nhà hàng</span>}
              value={restaurants?.length || 0}
              prefix={<ShopOutlined style={{ color: '#D4663A' }} />}
              valueStyle={{ color: '#D4663A', fontSize: '28px' }}
            />
          </Card>
        </Col>

        <Col xs={24} sm={12} lg={6}>
          <Card
            hoverable
            style={{
              background: '#faf4f0',
              borderLeft: '4px solid #E8956F',
              border: 'none',
            }}
          >
            <Statistic
              title={<span style={{ color: 'rgba(0, 0, 0, 0.65)' }}>Chi nhánh</span>}
              value={branches?.length || 0}
              prefix={<TeamOutlined style={{ color: '#E8956F' }} />}
              valueStyle={{ color: '#E8956F', fontSize: '28px' }}
            />
          </Card>
        </Col>

        <Col xs={24} sm={12} lg={6}>
          <Card
            hoverable
            style={{
              background: '#ecf3f8',
              borderLeft: '4px solid #6BA3D8',
              border: 'none',
            }}
          >
            <Statistic
              title={<span style={{ color: 'rgba(0, 0, 0, 0.65)' }}>Tổng đặt bàn</span>}
              value={stats?.totalBookings || 0}
              prefix={<CalendarOutlined style={{ color: '#6BA3D8' }} />}
              valueStyle={{ color: '#6BA3D8', fontSize: '28px' }}
            />
          </Card>
        </Col>

        <Col xs={24} sm={12} lg={6}>
          <Card
            hoverable
            style={{
              background: '#fef8f0',
              borderLeft: '4px solid #F4A460',
              border: 'none',
            }}
          >
            <Statistic
              title={<span style={{ color: 'rgba(0, 0, 0, 0.65)' }}>Đang chờ</span>}
              value={stats?.pendingBookings || 0}
              prefix={<ClockCircleOutlined style={{ color: '#F4A460' }} />}
              valueStyle={{ color: '#F4A460', fontSize: '28px' }}
            />
          </Card>
        </Col>
      </Row>

      {/* Secondary Stats */}
      <Row gutter={[16, 16]} style={{ marginBottom: '32px' }}>
        <Col xs={24} sm={12} lg={8}>
          <Card>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div>
                <p style={{ margin: 0, color: 'rgba(0, 0, 0, 0.45)', fontSize: '12px' }}>
                  Đã xác nhận
                </p>
                <p style={{ margin: '8px 0 0 0', fontSize: '24px', fontWeight: 600, color: '#52c41a' }}>
                  {stats?.confirmedBookings || 0}
                </p>
              </div>
              <CheckCircleOutlined style={{ fontSize: '32px', color: '#52c41a' }} />
            </div>
          </Card>
        </Col>

        <Col xs={24} sm={12} lg={8}>
          <Card>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div>
                <p style={{ margin: 0, color: 'rgba(0, 0, 0, 0.45)', fontSize: '12px' }}>
                  Đã hoàn thành
                </p>
                <p style={{ margin: '8px 0 0 0', fontSize: '24px', fontWeight: 600, color: '#1677ff' }}>
                  {bookings?.filter((b) => b.status === 'completed').length || 0}
                </p>
              </div>
              <CheckCircleOutlined style={{ fontSize: '32px', color: '#1677ff' }} />
            </div>
          </Card>
        </Col>

        <Col xs={24} sm={12} lg={8}>
          <Card>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div>
                <p style={{ margin: 0, color: 'rgba(0, 0, 0, 0.45)', fontSize: '12px' }}>
                  Đã hủy
                </p>
                <p style={{ margin: '8px 0 0 0', fontSize: '24px', fontWeight: 600, color: '#ff4d4f' }}>
                  {stats?.cancelledBookings || 0}
                </p>
              </div>
              <CloseCircleOutlined style={{ fontSize: '32px', color: '#ff4d4f' }} />
            </div>
          </Card>
        </Col>
      </Row>

      {/* Recent Bookings */}
      <Card
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <CalendarOutlined />
            <span>Đặt bàn gần đây</span>
          </div>
        }
        style={{ marginBottom: '32px' }}
      >
        {recentBookings && recentBookings.length > 0 ? (
          <Table
            columns={bookingColumns}
            dataSource={recentBookings}
            rowKey="id"
            pagination={false}
            scroll={{ x: 800 }}
            style={{ width: '100%' }}
          />
        ) : (
          <Empty description="Không có đặt bàn gần đây" />
        )}
      </Card>

      {/* Quick Stats Summary */}
      <Card style={{ background: '#f6ede5', border: '1px solid #e8ddd0', borderRadius: '8px' }}>
        <Row gutter={[32, 32]}>
          <Col xs={24} sm={12} lg={6}>
            <div>
              <p style={{ margin: 0, color: 'rgba(0, 0, 0, 0.65)', fontSize: '12px' }}>Tỉ lệ hoàn thành</p>
              <p style={{ margin: '8px 0 0 0', fontSize: '20px', fontWeight: 600, color: '#D4663A' }}>
                {stats?.totalBookings ? Math.round(((bookings?.filter(b => b.status === 'completed').length || 0) / stats.totalBookings) * 100) : 0}%
              </p>
            </div>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <div>
              <p style={{ margin: 0, color: 'rgba(0, 0, 0, 0.65)', fontSize: '12px' }}>Tỉ lệ xác nhận</p>
              <p style={{ margin: '8px 0 0 0', fontSize: '20px', fontWeight: 600, color: '#D4663A' }}>
                {stats?.totalBookings ? Math.round(((stats.confirmedBookings || 0) / stats.totalBookings) * 100) : 0}%
              </p>
            </div>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <div>
              <p style={{ margin: 0, color: 'rgba(0, 0, 0, 0.65)', fontSize: '12px' }}>Tỉ lệ hủy</p>
              <p style={{ margin: '8px 0 0 0', fontSize: '20px', fontWeight: 600, color: '#D4663A' }}>
                {stats?.totalBookings ? Math.round(((stats.cancelledBookings || 0) / stats.totalBookings) * 100) : 0}%
              </p>
            </div>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <div>
              <p style={{ margin: 0, color: 'rgba(0, 0, 0, 0.65)', fontSize: '12px' }}>Chi nhánh/nhà hàng</p>
              <p style={{ margin: '8px 0 0 0', fontSize: '20px', fontWeight: 600, color: '#D4663A' }}>
                {branches?.length && restaurants?.length
                  ? (branches.length / restaurants.length).toFixed(1)
                  : 0}
              </p>
            </div>
          </Col>
        </Row>
      </Card>
    </div>
  )
}
