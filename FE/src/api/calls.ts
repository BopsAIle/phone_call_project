import { axiosInstance } from './axios'
import { Call, CallFilters, CallWithTranscript } from '../types'

interface ApiResponse<T> {
  success: boolean
  message: string
  data: T
  timestamp: string
  path: string
}

export const callApi = {
  /** BE trả 100 cuộc gọi gần nhất, mới nhất lên đầu. */
  getAll: async (filters: CallFilters = {}) => {
    const response = await axiosInstance.get<ApiResponse<Call[]>>('/calls', {
      params: {
        restaurant_id: filters.restaurant_id,
        branch_id: filters.branch_id,
        status: filters.status,
      },
    })
    return response.data.data
  },

  /** Chi tiết cuộc gọi kèm toàn bộ transcript. */
  getById: async (id: string) => {
    const response = await axiosInstance.get<ApiResponse<CallWithTranscript>>(`/calls/${id}`)
    return response.data.data
  },

  /** Tra theo mã của nhà mạng — dùng khi chỉ có mã trong log. */
  getByCallId: async (callId: string) => {
    const response = await axiosInstance.get<ApiResponse<Call>>(`/calls/by-call-id/${callId}`)
    return response.data.data
  },
}
