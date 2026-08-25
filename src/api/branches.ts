import { axiosInstance } from './axios'
import { Branch, CreateBranchDto, UpdateBranchDto, BranchStatus } from '../types'

interface ApiResponse<T> {
  success: boolean
  message: string
  data: T
  timestamp: string
  path: string
}

export const branchApi = {
  getAll: async (status?: BranchStatus, restaurantId?: string) => {
    const response = await axiosInstance.get<ApiResponse<Branch[]>>('/branches', {
      params: { status, restaurant_id: restaurantId },
    })
    return response.data.data
  },

  getById: async (id: string) => {
    const response = await axiosInstance.get<ApiResponse<Branch>>(`/branches/${id}`)
    return response.data.data
  },

  getByRestaurant: async (restaurantId: string) => {
    const response = await axiosInstance.get<ApiResponse<Branch[]>>(`/restaurants/${restaurantId}/branches`)
    return response.data.data
  },

  create: async (data: CreateBranchDto) => {
    const response = await axiosInstance.post<ApiResponse<Branch>>('/branches', data)
    return response.data.data
  },

  update: async (id: string, data: UpdateBranchDto) => {
    const response = await axiosInstance.patch<ApiResponse<Branch>>(`/branches/${id}`, data)
    return response.data.data
  },

  delete: async (id: string) => {
    const response = await axiosInstance.delete<ApiResponse<{ message: string }>>(`/branches/${id}`)
    return response.data.data
  },

  getBranchCount: async (restaurantId: string) => {
    const response = await axiosInstance.get<ApiResponse<{ count: number }>>(
      `/branches/restaurant/${restaurantId}/count`
    )
    return response.data.data.count
  },
}
