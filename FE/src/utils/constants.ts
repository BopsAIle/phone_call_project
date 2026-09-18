export const APP_NAME = 'Restaurant AI Management'

export const RESTAURANT_STATUS_LABELS = {
  active: 'Đang hoạt động',
  inactive: 'Không hoạt động',
}

export const BOOKING_STATUS_LABELS = {
  pending: 'Chờ xác nhận',
  confirmed: 'Đã xác nhận',
  completed: 'Hoàn thành',
  cancelled: 'Hủy bỏ',
  no_show: 'Không xuất hiện',
}

export const BOOKING_SOURCE_LABELS = {
  website: 'Website',
  phone_ai: 'AI Voice',
  phone_human: 'Điện thoại',
  walk_in: 'Ghé quán',
  app: 'App',
  social_media: 'Mạng xã hội',
  third_party: 'Ngoài',
}

export const BRANCH_STATUS_LABELS = {
  active: 'Đang hoạt động',
  inactive: 'Không hoạt động',
  maintenance: 'Bảo trì',
}

export const CALL_STATUS_LABELS = {
  in_progress: 'Đang gọi',
  completed: 'Đã kết thúc',
  failed: 'Lỗi',
}

export const CALL_INTENT_LABELS = {
  unknown: 'Chưa rõ',
  booking: 'Đặt bàn',
  pickup: 'Mang về',
  delivery: 'Giao hàng',
}
