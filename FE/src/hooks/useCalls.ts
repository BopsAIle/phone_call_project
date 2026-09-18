import { useQuery } from '@tanstack/react-query'
import { callApi } from '../api'
import { CallFilters, CallStatus, CallWithTranscript } from '../types'

/** Danh sách cuộc gọi. Tự làm mới mỗi 15 s để cuộc gọi đang chạy hiện ra mà không cần bấm. */
export const useCalls = (filters: CallFilters = {}) => {
  return useQuery({
    queryKey: ['calls', filters.restaurant_id, filters.branch_id, filters.status],
    queryFn: () => callApi.getAll(filters),
    refetchInterval: 15000,
  })
}

/**
 * Một cuộc gọi kèm transcript.
 *
 * Cuộc gọi đang chạy thì AI còn đẩy transcript lên theo lô (10 câu hoặc 30 s một lần),
 * nên chỉ lúc đó mới hỏi lại BE mỗi 5 s; gọi đã chốt thì dữ liệu không đổi nữa.
 *
 * `live` tắt nhịp hỏi lại khi người xem đã đóng cửa sổ — dữ liệu vẫn nằm trong cache để
 * lúc modal mờ dần đi không bị nháy sang trạng thái trống.
 */
export const useCall = (id?: string, live: boolean = true) => {
  return useQuery({
    queryKey: ['call', id],
    queryFn: () => callApi.getById(id as string),
    enabled: !!id,
    refetchInterval: (query) => {
      if (!live) return false
      const call = query.state.data as CallWithTranscript | undefined
      return call?.status === CallStatus.IN_PROGRESS ? 5000 : false
    },
  })
}
