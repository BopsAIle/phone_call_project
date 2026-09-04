export const formatPrice = (price: number | undefined | null): string => {
  if (price === undefined || price === null) return '0 đ'
  return `${Math.floor(price).toLocaleString('vi-VN', { maximumFractionDigits: 0 })} đ`
}
