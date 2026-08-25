import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { branchApi } from '../api'
import { BranchStatus } from '../types'

export const useBranches = (status?: BranchStatus, restaurantId?: string) => {
  return useQuery({
    queryKey: ['branches', status, restaurantId],
    queryFn: () => branchApi.getAll(status, restaurantId),
  })
}

export const useBranch = (id: string) => {
  return useQuery({
    queryKey: ['branch', id],
    queryFn: () => branchApi.getById(id),
    enabled: !!id,
  })
}

export const useBranchesByRestaurant = (restaurantId: string) => {
  return useQuery({
    queryKey: ['branches', 'restaurant', restaurantId],
    queryFn: () => branchApi.getByRestaurant(restaurantId),
    enabled: !!restaurantId,
  })
}

export const useCreateBranch = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: branchApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['branches'] })
    },
  })
}

export const useUpdateBranch = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: any }) => branchApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['branches'] })
    },
  })
}

export const useDeleteBranch = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: branchApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['branches'] })
    },
  })
}
