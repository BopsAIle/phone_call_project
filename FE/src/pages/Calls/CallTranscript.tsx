import React, { useMemo, useState } from 'react'
import { Modal, Descriptions, Tag, Switch, Button, Empty, Spin, Space, Typography, message } from 'antd'
import { CopyOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { useCall } from '../../hooks'
import { CallIntent, CallMessage, CallMessageRole, CallStatus, CallWithTranscript } from '../../types'
import { CALL_INTENT_LABELS, CALL_STATUS_LABELS } from '../../utils/constants'
import { formatDuration } from '../../utils/formatDuration'

interface CallTranscriptProps {
  callId?: string
  open: boolean
  onClose: () => void
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

const roleLabels: Record<CallMessageRole, string> = {
  [CallMessageRole.USER]: 'Khách',
  [CallMessageRole.ASSISTANT]: 'AI',
  [CallMessageRole.TOOL]: 'Công cụ',
}

/** "+1:05" tính từ lúc bắt đầu cuộc gọi — dễ đối chiếu với file ghi âm hơn giờ tuyệt đối. */
const offsetLabel = (spokenAt?: string | null, startedAt?: string | null): string => {
  if (!spokenAt) return ''
  if (!startedAt) return dayjs(spokenAt).format('HH:mm:ss')
  const delta = dayjs(spokenAt).diff(dayjs(startedAt), 'second')
  if (delta < 0) return dayjs(spokenAt).format('HH:mm:ss')
  return `+${formatDuration(delta)}`
}

/** Kết quả tool là JSON một dòng; in ra cho dễ đọc, hỏng thì trả nguyên văn. */
const prettyJson = (raw: string): string => {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return raw
  }
}

const Bubble: React.FC<{ message: CallMessage; startedAt?: string | null }> = ({
  message: entry,
  startedAt,
}) => {
  const offset = offsetLabel(entry.spoken_at, startedAt)

  if (entry.role === CallMessageRole.TOOL) {
    return (
      <div style={{ margin: '12px 0', display: 'flex', justifyContent: 'center' }}>
        <div
          style={{
            width: '100%',
            maxWidth: 620,
            background: '#fffbe6',
            border: '1px solid #ffe58f',
            borderRadius: 8,
            padding: '8px 12px',
          }}
        >
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
            <Tag color="gold" style={{ margin: 0 }}>
              {entry.tool_name || 'công cụ'}
            </Tag>
            <span style={{ fontSize: 12, color: 'rgba(0, 0, 0, 0.45)' }}>{offset}</span>
          </div>
          <pre
            style={{
              margin: 0,
              fontSize: 12,
              lineHeight: 1.5,
              maxHeight: 200,
              overflow: 'auto',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              color: 'rgba(0, 0, 0, 0.65)',
            }}
          >
            {prettyJson(entry.content)}
          </pre>
        </div>
      </div>
    )
  }

  const isAgent = entry.role === CallMessageRole.ASSISTANT

  return (
    <div
      style={{
        display: 'flex',
        justifyContent: isAgent ? 'flex-end' : 'flex-start',
        margin: '12px 0',
      }}
    >
      <div style={{ maxWidth: '72%' }}>
        <div
          style={{
            fontSize: 12,
            color: 'rgba(0, 0, 0, 0.45)',
            marginBottom: 4,
            textAlign: isAgent ? 'right' : 'left',
          }}
        >
          {roleLabels[entry.role]}
          {offset ? ` · ${offset}` : ''}
        </div>
        <div
          style={{
            background: isAgent ? '#e6f4ff' : '#f5f5f5',
            border: `1px solid ${isAgent ? '#bae0ff' : '#f0f0f0'}`,
            borderRadius: 10,
            padding: '10px 14px',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            lineHeight: 1.6,
          }}
        >
          {entry.content}
        </div>
      </div>
    </div>
  )
}

export const CallTranscript: React.FC<CallTranscriptProps> = ({ callId, open, onClose }) => {
  const [showTools, setShowTools] = useState(false)
  const { data: call, isLoading, isError } = useCall(callId, open)

  const messages = useMemo<CallMessage[]>(() => {
    const all = (call as CallWithTranscript | undefined)?.messages ?? []
    return showTools ? all : all.filter((entry) => entry.role !== CallMessageRole.TOOL)
  }, [call, showTools])

  const handleCopy = async () => {
    if (!call) return
    const lines = messages.map((entry) => {
      const head = offsetLabel(entry.spoken_at, call.started_at)
      const who = entry.role === CallMessageRole.TOOL
        ? `Công cụ ${entry.tool_name || ''}`.trim()
        : roleLabels[entry.role]
      return `${head ? `[${head}] ` : ''}${who}: ${entry.content}`
    })
    try {
      await navigator.clipboard.writeText(lines.join('\n'))
      message.success('Đã sao chép hội thoại')
    } catch {
      message.error('Trình duyệt không cho sao chép, bạn bôi đen và copy tay giúp nhé')
    }
  }

  const renderBody = () => {
    if (isLoading) {
      return (
        <div style={{ display: 'flex', justifyContent: 'center', padding: '48px 0' }}>
          <Spin size="large" />
        </div>
      )
    }
    if (isError || !call) {
      return <Empty description="Không tải được cuộc gọi này" />
    }

    const all = (call as CallWithTranscript).messages ?? []

    return (
      <div>
        <Descriptions size="small" bordered column={{ xs: 1, sm: 2 }} style={{ marginBottom: 16 }}>
          <Descriptions.Item label="Mã cuộc gọi">
            <Typography.Text copyable style={{ fontFamily: 'monospace', fontSize: 12 }}>
              {call.call_id}
            </Typography.Text>
          </Descriptions.Item>
          <Descriptions.Item label="Trạng thái">
            <Tag color={statusColors[call.status]}>{CALL_STATUS_LABELS[call.status]}</Tag>
            <Tag color={intentColors[call.intent]}>{CALL_INTENT_LABELS[call.intent]}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Số khách gọi">{call.from_number || '—'}</Descriptions.Item>
          <Descriptions.Item label="Hotline nhận">{call.to_number || '—'}</Descriptions.Item>
          <Descriptions.Item label="Nhà hàng">{call.store_name || '—'}</Descriptions.Item>
          <Descriptions.Item label="Thời lượng">
            {formatDuration(call.duration_seconds)}
          </Descriptions.Item>
          <Descriptions.Item label="Bắt đầu">
            {call.started_at ? dayjs(call.started_at).format('DD/MM/YYYY HH:mm:ss') : '—'}
          </Descriptions.Item>
          <Descriptions.Item label="Kết thúc">
            {call.ended_at ? dayjs(call.ended_at).format('DD/MM/YYYY HH:mm:ss') : '—'}
          </Descriptions.Item>
          {(call.booking_id || call.order_id) && (
            <Descriptions.Item label="Đơn tạo ra" span={2}>
              <Space size="small" wrap>
                {call.booking_id && <Tag color="blue">Đặt bàn: {call.booking_id}</Tag>}
                {call.order_id && <Tag color="purple">Đặt món: {call.order_id}</Tag>}
              </Space>
            </Descriptions.Item>
          )}
          {call.end_reason && (
            <Descriptions.Item label="Lý do kết thúc" span={2}>
              {call.end_reason}
            </Descriptions.Item>
          )}
        </Descriptions>

        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 8,
          }}
        >
          <Space size="small">
            <Switch size="small" checked={showTools} onChange={setShowTools} />
            <span style={{ fontSize: 13, color: 'rgba(0, 0, 0, 0.65)' }}>
              Hiện bước gọi công cụ
            </span>
          </Space>
          <Space size="small">
            {call.status === CallStatus.IN_PROGRESS && (
              <Tag color="processing">Đang gọi — transcript còn chảy về</Tag>
            )}
            <Button size="small" icon={<CopyOutlined />} onClick={handleCopy} disabled={!messages.length}>
              Sao chép
            </Button>
          </Space>
        </div>

        <div
          style={{
            maxHeight: '48vh',
            overflowY: 'auto',
            background: '#fafafa',
            border: '1px solid #f0f0f0',
            borderRadius: 8,
            padding: '8px 16px',
          }}
        >
          {messages.length === 0 ? (
            <Empty
              style={{ padding: '24px 0' }}
              description={
                all.length
                  ? 'Cuộc gọi này chỉ có bước gọi công cụ — bật công tắc ở trên để xem'
                  : 'Cuộc gọi này chưa có câu nào được lưu'
              }
            />
          ) : (
            messages.map((entry) => (
              <Bubble key={entry.id ?? entry.sequence} message={entry} startedAt={call.started_at} />
            ))
          )}
        </div>
      </div>
    )
  }

  return (
    <Modal
      title="Hội thoại cuộc gọi"
      open={open}
      onCancel={onClose}
      footer={null}
      width={860}
    >
      {renderBody()}
    </Modal>
  )
}
