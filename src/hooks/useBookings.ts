import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { bookingApi } from '../api'
import { BookingStatus, BookingSource } from '../types'

export const useBookings = (
  status?: BookingStatus,
  source?: BookingSource,
  restaurantId?: string,
  branchId?: string
) => {
  return useQuery({
    queryKey: ['bookings', status, source, restaurantId, branchId],
    queryFn: () => bookingApi.getAll(status, source, restaurantId, branchId),
  })
}

export const useBooking = (id: string) => {
  return useQuery({
    queryKey: ['booking', id],
    queryFn: () => bookingApi.getById(id),
    enabled: !!id,
  })
}

export const useBookingsByBranchAndDate = (branchId: string, date: string) => {
  return useQuery({
    queryKey: ['bookings', 'branch', branchId, 'date', date],
    queryFn: () => bookingApi.getByBranchAndDate(branchId, date),
    enabled: !!branchId && !!date,
  })
}

export const useBookingStats = () => {
  return useQuery({
    queryKey: ['bookings', 'stats'],
    queryFn: () => bookingApi.getStats(),
  })
}

export const useCreateBooking = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: bookingApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bookings'] })
    },
  })
}

export const useUpdateBooking = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: any }) => bookingApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bookings'] })
    },
  })
}

export const useDeleteBooking = () => {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: bookingApi.delete,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bookings'] })
    },
  })
}
