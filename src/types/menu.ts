export enum MenuItemStatus {
  AVAILABLE = 'available',
  UNAVAILABLE = 'unavailable',
  SOLD_OUT = 'sold_out',
}

export enum BookingType {
  DINE_IN = 'dine_in',
  TAKEOUT = 'takeout',
  DELIVERY = 'delivery',
}

export enum ShipperStatus {
  PENDING = 'pending',
  ASSIGNED = 'assigned',
  PICKED_UP = 'picked_up',
  ON_THE_WAY = 'on_the_way',
  DELIVERED = 'delivered',
  CANCELLED = 'cancelled',
}

export interface MenuItem {
  id: string
  branch_id: string
  name: string
  description?: string
  price: number
  status: MenuItemStatus
  quantity_available: number
  created_at: string
  updated_at: string
}

export interface OrderItem {
  id: string
  booking_id: string
  menu_item_id: string
  quantity: number
  unit_price: number
  subtotal: number
  created_at: string
  updated_at: string
  menu_item?: MenuItem
}

export interface CreateMenuItemDto {
  branch_id: string
  name: string
  description?: string
  price: number
  quantity_available?: number
}

export interface UpdateMenuItemDto {
  name?: string
  description?: string
  price?: number
  status?: MenuItemStatus
  quantity_available?: number
}

export interface OrderItemInput {
  menu_item_id: string
  quantity: number
}

export interface CreateTakeoutBookingDto {
  restaurant_id: string
  branch_id: string
  customer_name: string
  customer_phone: string
  booking_date: string
  booking_time: string
  items: OrderItemInput[]
  note?: string
}

export interface CreateDeliveryBookingDto {
  restaurant_id: string
  branch_id: string
  customer_name: string
  customer_phone: string
  booking_date: string
  booking_time: string
  items: OrderItemInput[]
  delivery_address: string
  delivery_phone?: string
  delivery_fee: number
  estimated_delivery_time: string
  note?: string
}

export interface TakeoutBookingResponse {
  id: string
  restaurant_id: string
  branch_id: string
  customer_name: string
  phone_number: string
  booking_date: string
  booking_time: string
  booking_type: BookingType
  party_size: number
  total_price: number
  note: string
  status: string
  source: string
  order_items: OrderItem[]
  created_at: string
  updated_at: string
}

export interface DeliveryBookingResponse {
  id: string
  restaurant_id: string
  branch_id: string
  customer_name: string
  phone_number: string
  booking_date: string
  booking_time: string
  booking_type: BookingType
  party_size: number
  total_price: number
  note: string
  status: string
  source: string
  delivery_address: string
  delivery_phone: string
  delivery_fee: number
  estimated_delivery_time: string
  actual_delivery_time?: string
  shipper_status: ShipperStatus
  order_items: OrderItem[]
  created_at: string
  updated_at: string
}
