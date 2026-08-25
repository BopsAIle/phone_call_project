export enum BranchStatus {
  ACTIVE = 'active',
  INACTIVE = 'inactive',
  MAINTENANCE = 'maintenance',
}

export interface Branch {
  id: string
  restaurant_id: string
  name: string
  phone: string
  address: string
  opening_time: string
  closing_time: string
  status: BranchStatus
  created_at: string
  updated_at: string
}

export interface CreateBranchDto {
  restaurant_id: string
  name: string
  phone: string
  address: string
  opening_time: string
  closing_time: string
}

export interface UpdateBranchDto {
  name?: string
  phone?: string
  address?: string
  opening_time?: string
  closing_time?: string
  status?: BranchStatus
}
