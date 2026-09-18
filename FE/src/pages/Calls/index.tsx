import React, { useState } from 'react'
import { Button, Card, Col, Input, Row, Select } from 'antd'
import { ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import { CallList } from './CallList'
import { useBranches, useRestaurants } from '../../hooks'
import { CallStatus } from '../../types'
import { CALL_STATUS_LABELS } from '../../utils/constants'

export const CallsPage: React.FC = () => {
  const [restaurantId, setRestaurantId] = useState<string | undefined>()
  const [branchId, setBranchId] = useState<string | undefined>()
  const [status, setStatus] = useState<CallStatus | undefined>()
  const [search, setSearch] = useState('')

  const queryClient = useQueryClient()
  const { data: restaurants = [] } = useRestaurants()
  const { data: branches = [] } = useBranches(undefined, restaurantId)

  const handleRestaurantChange = (value?: string) => {
    setRestaurantId(value)
    // Chi nhánh cũ thuộc nhà hàng khác thì lọc ra rỗng, nên bỏ luôn cho khỏi khó hiểu.
    setBranchId(undefined)
  }

  return (
    <div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '24px',
          paddingBottom: '16px',
          borderBottom: '1px solid #f0f0f0',
        }}
      >
        <div>
          <h2 style={{ margin: 0, fontSize: '24px', fontWeight: 600, color: '#001529' }}>
            Lịch sử cuộc gọi
          </h2>
          <p style={{ margin: '8px 0 0 0', color: 'rgba(0, 0, 0, 0.45)', fontSize: '14px' }}>
            Xem lại hội thoại giữa khách và tổng đài AI — thứ để đối chiếu khi khách khiếu nại đơn
          </p>
        </div>
        <Button
          size="large"
          icon={<ReloadOutlined />}
          onClick={() => queryClient.invalidateQueries({ queryKey: ['calls'] })}
          style={{ borderRadius: '6px' }}
        >
          Tải lại
        </Button>
      </div>

      <Card>
        <Row gutter={[16, 16]} style={{ marginBottom: '16px' }}>
          <Col xs={24} sm={12} md={6}>
            <Select
              placeholder="Lọc theo nhà hàng"
              allowClear
              showSearch
              optionFilterProp="label"
              value={restaurantId}
              onChange={handleRestaurantChange}
              style={{ width: '100%' }}
              options={restaurants.map((restaurant) => ({
                label: restaurant.name,
                value: restaurant.id,
              }))}
            />
          </Col>

          <Col xs={24} sm={12} md={6}>
            <Select
              placeholder="Lọc theo chi nhánh"
              allowClear
              showSearch
              optionFilterProp="label"
              value={branchId}
              onChange={setBranchId}
              style={{ width: '100%' }}
              options={branches.map((branch) => ({ label: branch.name, value: branch.id }))}
            />
          </Col>

          <Col xs={24} sm={12} md={5}>
            <Select
              placeholder="Lọc theo trạng thái"
              allowClear
              value={status}
              onChange={setStatus}
              style={{ width: '100%' }}
              options={[
                { label: CALL_STATUS_LABELS.in_progress, value: CallStatus.IN_PROGRESS },
                { label: CALL_STATUS_LABELS.completed, value: CallStatus.COMPLETED },
                { label: CALL_STATUS_LABELS.failed, value: CallStatus.FAILED },
              ]}
            />
          </Col>

          <Col xs={24} sm={12} md={7}>
            <Input
              placeholder="Tìm theo số điện thoại hoặc mã cuộc gọi"
              allowClear
              prefix={<SearchOutlined style={{ color: 'rgba(0, 0, 0, 0.25)' }} />}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </Col>
        </Row>

        <CallList
          filters={{ restaurant_id: restaurantId, branch_id: branchId, status }}
          search={search}
        />
      </Card>
    </div>
  )
}
