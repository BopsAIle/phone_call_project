import { axiosInstance } from './axios'
import {
  MenuItem,
  MenuItemStatus,
  CreateMenuItemDto,
  UpdateMenuItemDto,
  CreateTakeoutBookingDto,
  CreateDeliveryBookingDto,
  TakeoutBookingResponse,
  DeliveryBookingResponse,
  OrderItem,
} from '../types'

interface ApiResponse<T> {
  success: boolean
  message: string
  data: T
  timestamp: string
  path: string
}

export const menuApi = {
  // ===== MENU ITEMS =====
  
  getAllMenuItems: async (branchId?: string) => {
    const response = await axiosInstance.get<ApiResponse<MenuItem[]>>('/menu', {
      params: branchId ? { branch_id: branchId } : undefined,
    })
    return response.data.data
  },

  getMenuByBranchId: async (branchId: string) => {
    const response = await axiosInstance.get<ApiResponse<MenuItem[]>>(`/menu/branch/${branchId}`)
    return response.data.data
  },

  getMenuItemById: async (id: string) => {
    const response = await axiosInstance.get<ApiResponse<MenuItem>>(`/menu/${id}`)
    return response.data.data
  },

  createMenuItem: async (data: CreateMenuItemDto) => {
    const response = await axiosInstance.post<ApiResponse<MenuItem>>('/menu', data)
    return response.data.data
  },

  updateMenuItem: async (id: string, data: UpdateMenuItemDto) => {
    const response = await axiosInstance.patch<ApiResponse<MenuItem>>(`/menu/${id}`, data)
    return response.data.data
  },

  deleteMenuItem: async (id: string) => {
    const response = await axiosInstance.delete<ApiResponse<{ message: string }>>(`/menu/${id}`)
    return response.data.data
  },

  // ===== TAKEOUT BOOKINGS =====

  createTakeoutBooking: async (data: CreateTakeoutBookingDto) => {
    const response = await axiosInstance.post<ApiResponse<TakeoutBookingResponse>>(
      '/menu/takeout/ai',
      data
    )
    return response.data.data
  },

  confirmTakeoutBooking: async (bookingId: string) => {
    const response = await axiosInstance.patch<ApiResponse<TakeoutBookingResponse>>(
      `/menu/takeout/${bookingId}/confirm`
    )
    return response.data.data
  },

  // ===== DELIVERY BOOKINGS =====

  createDeliveryBooking: async (data: CreateDeliveryBookingDto) => {
    const response = await axiosInstance.post<ApiResponse<DeliveryBookingResponse>>(
      '/menu/delivery/ai',
      data
    )
    return response.data.data
  },

  confirmDeliveryBooking: async (bookingId: string) => {
    const response = await axiosInstance.patch<ApiResponse<DeliveryBookingResponse>>(
      `/menu/delivery/${bookingId}/confirm`
    )
    return response.data.data
  },

  // ===== ORDER ITEMS =====

  getOrderItems: async (bookingId: string) => {
    const response = await axiosInstance.get<ApiResponse<OrderItem[]>>(
      `/menu/order/${bookingId}/items`
    )
    return response.data.data
  },
}
