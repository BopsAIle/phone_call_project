import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { menuApi } from '../api'
import {
  CreateMenuItemDto,
  UpdateMenuItemDto,
  CreateTakeoutBookingDto,
  CreateDeliveryBookingDto,
} from '../types'

// ===== MENU ITEMS HOOKS =====

export const useMenuItems = (branchId?: string) => {
  return useQuery({
    queryKey: ['menu-items', branchId],
    queryFn: () => (branchId ? menuApi.getMenuByBranchId(branchId) : menuApi.getAllMenuItems()),
    enabled: !!branchId,
  })
}

export const useMenuItemsByBranch = (branchId: string) => {
  return useQuery({
    queryKey: ['menu-items', 'branch', branchId],
    queryFn: () => menuApi.getMenuByBranchId(branchId),
    enabled: !!branchId,
  })
}

export const useMenuItem = (id: string) => {
  return useQuery({
    queryKey: ['menu-item', id],
    queryFn: () => menuApi.getMenuItemById(id),
    enabled: !!id,
  })
}

export const useCreateMenuItem = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: CreateMenuItemDto) => menuApi.createMenuItem(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['menu-items'] })
    },
  })
}

export const useUpdateMenuItem = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateMenuItemDto }) =>
      menuApi.updateMenuItem(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['menu-items'] })
    },
  })
}

export const useDeleteMenuItem = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (id: string) => menuApi.deleteMenuItem(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['menu-items'] })
    },
  })
}

// ===== TAKEOUT BOOKINGS HOOKS =====

export const useCreateTakeoutBooking = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: CreateTakeoutBookingDto) => menuApi.createTakeoutBooking(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bookings'] })
    },
  })
}

export const useConfirmTakeoutBooking = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (bookingId: string) => menuApi.confirmTakeoutBooking(bookingId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bookings'] })
      queryClient.invalidateQueries({ queryKey: ['menu-items'] })
    },
  })
}

// ===== DELIVERY BOOKINGS HOOKS =====

export const useCreateDeliveryBooking = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: CreateDeliveryBookingDto) => menuApi.createDeliveryBooking(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bookings'] })
    },
  })
}

export const useConfirmDeliveryBooking = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (bookingId: string) => menuApi.confirmDeliveryBooking(bookingId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bookings'] })
      queryClient.invalidateQueries({ queryKey: ['menu-items'] })
    },
  })
}

// ===== ORDER ITEMS HOOKS =====

export const useOrderItems = (bookingId: string) => {
  return useQuery({
    queryKey: ['order-items', bookingId],
    queryFn: () => menuApi.getOrderItems(bookingId),
    enabled: !!bookingId,
  })
}
