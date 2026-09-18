import React, { useMemo, useState } from 'react'
import { Table, Tag, Button, Space, Empty } from 'antd'
import { EyeOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { useCalls } from '../../hooks'
import { LoadingSpinner } from '../../components'
import { Call, CallFilters, CallIntent, CallStatus } from '../../types'
import { CALL_INTENT_LABELS, CALL_STATUS_LABELS } from '../../utils/constants'
import { formatDuration } from '../../utils/formatDuration'
import { CallTranscript } from './CallTranscript'

interface CallListProps {
  filters?: CallFilters
  /** Lọc thêm ở phía trình duyệt: số điện thoại, mã cuộc gọi, tên nhà hàng. */
  search?: string
}

const statusColors: Record<CallStatus, string> = {
  [CallStatus.IN_PROGRESS]: 'processing',
  [CallStatus.COMPLETED]: 'green',
  [CallStatus.FAILED]: 'red',
}

const intentColors: Record<CallIntent, string> = {
  [CallIntent.UNKNOWN]: 'default',
  [CallIntent.BOOKING]: 'blue',
  [CallIntent.PICKUP]: 'orange',
  [CallIntent.DELIVERY]: 'purple',
}

export const CallList: React.FC<CallListProps> = ({ filters = {}, search = '' }) => {
  const [detail, setDetail] = useState<{ open: boolean; callId?: string }>({ open: false })
  const { data: calls, isLoading } = useCalls(filters)

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase()
    if (!needle) return calls ?? []
    return (calls ?? []).filter((call) =>
      [call.from_number, call.to_number, call.call_id, call.store_name]
        .filter(Boolean)
        .some((field) => String(field).toLowerCase().includes(needle)),
    )
  }, [calls, search])

  const columns = [
    {
      title: 'Thời điểm gọi',
      dataIndex: 'started_at',
      key: 'started_at',
      width: 170,
      render: (value: string | null, record: Call) => {
        const at = value || record.created_at
        return at ? dayjs(at).format('DD/MM/YYYY HH:mm:ss') : '—'
      },
    },
    {
      title: 'Số khách gọi',
      dataIndex: 'from_number',
      key: 'from_number',
      width: 140,
      render: (value: string | null) => value || 'Không rõ',
    },
    {
      title: 'Nhà hàng',
      dataIndex: 'store_name',
      key: 'store_name',
      width: 180,
      render: (value: string | null) => value || '—',
    },
    {
      title: 'Mục đích',
      dataIndex: 'intent',
      key: 'intent',
      width: 120,
      render: (intent: CallIntent) => (
        <Tag color={intentColors[intent]}>{CALL_INTENT_LABELS[intent]}</Tag>
      ),
    },
    {
      title: 'Thời lượng',
      dataIndex: 'duration_seconds',
      key: 'duration_seconds',
      width: 110,
      render: (value: number | null) => formatDuration(value),
    },
    {
      title: 'Trạng thái',
      dataIndex: 'status',
      key: 'status',
      width: 140,
      render: (status: CallStatus) => (
        <Tag color={statusColors[status]}>{CALL_STATUS_LABELS[status]}</Tag>
      ),
    },
    {
      title: 'Kết quả',
      key: 'result',
      width: 130,
      render: (_: unknown, record: Call) => {
        if (record.booking_id) return <Tag color="blue">Đã đặt bàn</Tag>
        if (record.order_id) return <Tag color="purple">Đã đặt món</Tag>
        return <span style={{ color: 'rgba(0, 0, 0, 0.45)' }}>Không tạo đơn</span>
      },
    },
    {
      title: 'Hội thoại',
      key: 'action',
      width: 110,
      fixed: 'right' as const,
      render: (_: unknown, record: Call) => (
        <Space size="small">
          <Button
            type="primary"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => setDetail({ open: true, callId: record.id })}
          >
            Xem
          </Button>
        </Space>
      ),
    },
  ]

  if (isLoading) {
    return <LoadingSpinner />
  }

  return (
    <div>
      <Table
        columns={columns}
        dataSource={rows}
        rowKey="id"
        pagination={{ pageSize: 10, showSizeChanger: false }}
        scroll={{ x: 1100 }}
        locale={{
          emptyText: (
            <Empty
              description={
                search.trim()
                  ? 'Không có cuộc gọi nào khớp từ khoá'
                  : 'Chưa có cuộc gọi nào được lưu'
              }
            />
          ),
        }}
        onRow={(record) => ({
          onClick: () => setDetail({ open: true, callId: record.id }),
          style: { cursor: 'pointer' },
        })}
      />

      <CallTranscript
        callId={detail.callId}
        open={detail.open}
        // Giữ lại callId khi đóng: transcript còn trong cache nên lúc modal mờ dần
        // người xem không thấy nó nháy sang trạng thái trống.
        onClose={() => setDetail((prev) => ({ ...prev, open: false }))}
      />
    </div>
  )
}
