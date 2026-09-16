import { axiosInstance } from './axios'
import {
  Booking,
  CreateBookingDto,
  CreateAIBookingDto,
  UpdateBookingDto,
  BookingStatus,
  BookingSource,
  BookingStats,
} from '../types'

interface ApiResponse<T> {
  success: boolean
  message: string
  data: T
  timestamp: string
  path: string
}

export const bookingApi = {
  getAll: async (
    status?: BookingStatus,
    source?: BookingSource,
    restaurantId?: string,
    branchId?: string,
    phoneNumber?: string,
    startDate?: string,
    endDate?: string
  ) => {
    const response = await axiosInstance.get<ApiResponse<Booking[]>>('/bookings', {
      params: {
        status,
        source,
        restaurant_id: restaurantId,
        branch_id: branchId,
        phone_number: phoneNumber,
        start_date: startDate,
        end_date: endDate,
      },
    })
    return response.data.data
  },

  getById: async (id: string) => {
    const response = await axiosInstance.get<ApiResponse<Booking>>(`/bookings/${id}`)
    return response.data.data
  },

  getByRestaurant: async (restaurantId: string) => {
    const response = await axiosInstance.get<ApiResponse<Booking[]>>('/bookings', {
      params: { restaurant_id: restaurantId },
    })
    return response.data.data
  },

  getByBranch: async (branchId: string) => {
    const response = await axiosInstance.get<ApiResponse<Booking[]>>('/bookings', {
      params: { branch_id: branchId },
    })
    return response.data.data
  },

  getByBranchAndDate: async (branchId: string, date: string) => {
    const response = await axiosInstance.get<ApiResponse<Booking[]>>(`/bookings/branch/${branchId}/date/${date}`)
    return response.data.data
  },

  getStats: async () => {
    const response = await axiosInstance.get<ApiResponse<BookingStats>>('/bookings/stats')
    return response.data.data
  },

  create: async (data: CreateBookingDto) => {
    const response = await axiosInstance.post<ApiResponse<Booking>>('/bookings', data)
    return response.data.data
  },

  createFromAI: async (data: CreateAIBookingDto) => {
    const response = await axiosInstance.post<ApiResponse<Booking>>('/bookings/ai', data)
    return response.data.data
  },

  update: async (id: string, data: UpdateBookingDto) => {
    const response = await axiosInstance.patch<ApiResponse<Booking>>(`/bookings/${id}`, data)
    return response.data.data
  },

  delete: async (id: string) => {
    const response = await axiosInstance.delete<ApiResponse<{ message: string }>>(`/bookings/${id}`)
    return response.data.data
  },
}
