import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { restaurantApi } from '../api'
import { RestaurantStatus } from '../types'

export const useRestaurants = (status?: RestaurantStatus) => {
  return useQuery({
    queryKey: ['restaurants', status],
    queryFn: () => restaurantApi.getAll(status),
  })
}

export const useRestaurant = (id: string) => {
  return useQuery({
    queryKey: ['restaurant', id],
    queryFn: () => restaurantApi.getById(id),
    enabled: !!id,
  })
}

export const useCreateRestaurant = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: restaurantApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['restaurants'] })
    },
  })
}

export const useUpdateRestaurant = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: any }) =>
      restaurantApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['restaurants'] })
    },
  })
}

export const useDeleteRestaurant = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: restaurantApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['restaurants'] })
    },
  })
}
