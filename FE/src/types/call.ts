export enum CallStatus {
  IN_PROGRESS = 'in_progress',
  COMPLETED = 'completed',
  FAILED = 'failed',
}

export enum CallIntent {
  UNKNOWN = 'unknown',
  BOOKING = 'booking',
  PICKUP = 'pickup',
  DELIVERY = 'delivery',
}

export enum CallMessageRole {
  /** Câu khách nói, theo bản STT nghe được. */
  USER = 'user',
  /** Câu AI thật sự phát ra loa — câu bị khách cắt lời không nằm ở đây. */
  ASSISTANT = 'assistant',
  /** Một lần gọi công cụ và kết quả JSON của nó. */
  TOOL = 'tool',
}

export interface CallMessage {
  id: string
  call_id: string
  sequence: number
  role: CallMessageRole
  content: string
  tool_name?: string | null
  spoken_at?: string | null
  created_at: string
}

export interface Call {
  id: string
  /** Mã cuộc gọi do nhà mạng cấp. */
  call_id: string
  restaurant_id?: string | null
  branch_id?: string | null
  store_name?: string | null
  from_number?: string | null
  to_number?: string | null
  locale?: string | null
  status: CallStatus
  intent: CallIntent
  booking_id?: string | null
  order_id?: string | null
  started_at?: string | null
  ended_at?: string | null
  duration_seconds?: number | null
  end_reason?: string | null
  created_at: string
  updated_at: string
}

export interface CallWithTranscript extends Call {
  messages: CallMessage[]
}

export interface CallFilters {
  restaurant_id?: string
  branch_id?: string
  status?: CallStatus
}
