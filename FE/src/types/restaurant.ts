export enum RestaurantStatus {
  ACTIVE = 'active',
  INACTIVE = 'inactive',
}

export interface Restaurant {
  id: string
  name: string
  phone: string
  status: RestaurantStatus
  created_at: string
  updated_at: string
}

export interface CreateRestaurantDto {
  name: string
  phone: string
}

export interface UpdateRestaurantDto {
  name?: string
  phone?: string
  status?: RestaurantStatus
}
