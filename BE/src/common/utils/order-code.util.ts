import { BookingRepository } from '../../bookings/booking.repository';

export class OrderCodeUtil {
  static generateOrderCode(branchCode: string, counter: number): string {
    const today = new Date();
    const dateStr = today.toISOString().split('T')[0].replace(/-/g, '');
    const counterStr = String(counter).padStart(4, '0');
    return `ORD-${dateStr}-${branchCode}-${counterStr}`;
  }

  static async getNextCounter(
    bookingRepository: BookingRepository,
    branchId: string,
    today: Date,
  ): Promise<number> {
    const bookings = await bookingRepository.findByBranchId(branchId);
    const startOfDay = new Date(today);
    startOfDay.setHours(0, 0, 0, 0);

    const endOfDay = new Date(today);
    endOfDay.setHours(23, 59, 59, 999);

    const todaysBookings = bookings.filter(
      b => b.created_at >= startOfDay && b.created_at <= endOfDay
    );

    if (todaysBookings.length === 0) {
      return 1;
    }

    const lastBooking = todaysBookings.sort(
      (a, b) => b.created_at.getTime() - a.created_at.getTime()
    )[0];

    const counterMatch = lastBooking.order_code?.match(/(\d{4})$/);
    if (counterMatch) {
      return parseInt(counterMatch[1], 10) + 1;
    }

    return 1;
  }
}
