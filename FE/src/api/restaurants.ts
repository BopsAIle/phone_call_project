import { axiosInstance } from './axios'
import { Restaurant, CreateRestaurantDto, UpdateRestaurantDto, RestaurantStatus } from '../types'

interface ApiResponse<T> {
  success: boolean
  message: string
  data: T
  timestamp: string
  path: string
}

export const restaurantApi = {
  getAll: async (status?: RestaurantStatus) => {
    const response = await axiosInstance.get<ApiResponse<Restaurant[]>>('/restaurants', {
      params: { status },
    })
    return response.data.data
  },

  getById: async (id: string) => {
    const response = await axiosInstance.get<ApiResponse<Restaurant>>(`/restaurants/${id}`)
    return response.data.data
  },

  getByHotline: async (hotline: string) => {
    const response = await axiosInstance.get<ApiResponse<Restaurant>>(`/restaurants/by-hotline/${hotline}`)
    return response.data.data
  },

  create: async (data: CreateRestaurantDto) => {
    const response = await axiosInstance.post<ApiResponse<Restaurant>>('/restaurants', data)
    return response.data.data
  },

  update: async (id: string, data: UpdateRestaurantDto) => {
    const response = await axiosInstance.patch<ApiResponse<Restaurant>>(`/restaurants/${id}`, data)
    return response.data.data
  },

  delete: async (id: string) => {
    const response = await axiosInstance.delete<ApiResponse<{ message: string }>>(`/restaurants/${id}`)
    return response.data.data
  },
}
