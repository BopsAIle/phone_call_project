export enum BookingStatus {
  PENDING = 'pending',
  CONFIRMED = 'confirmed',
  CANCELLED = 'cancelled',
  COMPLETED = 'completed',
  NO_SHOW = 'no_show',
}

export enum BookingSource {
  WEBSITE = 'website',
  PHONE_AI = 'phone_ai',
  PHONE_HUMAN = 'phone_human',
  WALK_IN = 'walk_in',
  APP = 'app',
  SOCIAL_MEDIA = 'social_media',
  THIRD_PARTY = 'third_party',
}

export interface BookingRestaurant {
  id: string
  name: string
  phone: string
  status: string
  created_at: string
  updated_at: string
}

export interface BookingBranch {
  id: string
  restaurant_id: string
  name: string
  address: string
  phone: string
  opening_time: string
  closing_time: string
  status: string
  created_at: string
  updated_at: string
}

export interface Booking {
  id: string
  branch_id: string
  restaurant_id: string
  customer_name: string
  phone_number: string
  party_size: number
  booking_date: string
  booking_time: string
  note: string
  status: BookingStatus
  source: BookingSource
  created_at: string
  updated_at: string
  restaurant?: BookingRestaurant
  branch?: BookingBranch
}

export interface CreateBookingDto {
  restaurant_id: string
  branch_id: string
  customer_name: string
  phone_number: string
  party_size: number
  booking_date: string
  booking_time: string
  note?: string
}

export interface CreateAIBookingDto {
  branchPhone: string
  customer_name: string
  phone_number: string
  party_size: number
  booking_date: string
  booking_time: string
  note?: string
}

export interface UpdateBookingDto {
  status?: BookingStatus
  party_size?: number
  booking_date?: string
  booking_time?: string
  note?: string
  customer_name?: string
  phone_number?: string
}

export interface BookingStats {
  totalBookings: number
  pendingBookings: number
  confirmedBookings: number
  cancelledBookings: number
}
