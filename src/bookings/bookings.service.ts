import { Injectable, NotFoundException, BadRequestException, ConflictException } from '@nestjs/common';
import { Booking, BookingStatus, BookingSource } from './entities/booking.entity';
import { CreateBookingDto } from './dto/create-booking.dto';
import { CreateAIBookingDto } from './dto/create-ai-booking.dto';
import { UpdateBookingDto } from './dto/update-booking.dto';
import { BookingRepository } from './booking.repository';
import { RestaurantsService } from '../restaurants/restaurants.service';
import { BranchesService } from '../branches/branches.service';
import { RestaurantStatus } from '../restaurants/entities/restaurant.entity';
import { BranchStatus } from '../branches/entities/branch.entity';

@Injectable()
export class BookingsService {
  constructor(
    private readonly bookingRepository: BookingRepository,
    private readonly restaurantsService: RestaurantsService,
    private readonly branchesService: BranchesService,
  ) {}

  async create(createBookingDto: CreateBookingDto): Promise<Booking> {
    // Validate restaurant exists and is active
    const restaurant = await this.restaurantsService.findOne(createBookingDto.restaurant_id);
    if (restaurant.status !== RestaurantStatus.ACTIVE) {
      throw new BadRequestException('Nhà hàng hiện không hoạt động');
    }

    // Validate branch exists and is active
    const branch = await this.branchesService.findOne(createBookingDto.branch_id);
    if (branch.status !== BranchStatus.ACTIVE) {
      throw new BadRequestException('Chi nhánh hiện không hoạt động');
    }
    
    // Validate branch belongs to restaurant
    if (branch.restaurant_id !== createBookingDto.restaurant_id) {
      throw new BadRequestException('Chi nhánh không thuộc về nhà hàng được chọn');
    }

    // Validate booking date
    const bookingDate = new Date(createBookingDto.booking_date);
    bookingDate.setHours(0, 0, 0, 0);
    
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    
    if (bookingDate < today) {
      throw new BadRequestException('Không thể đặt bàn cho ngày trong quá khứ');
    }

    const maxDate = new Date();
    maxDate.setMonth(maxDate.getMonth() + 3);
    maxDate.setHours(0, 0, 0, 0);
    
    if (bookingDate > maxDate) {
      throw new BadRequestException('Chỉ có thể đặt bàn trong vòng 3 tháng tới');
    }

    // Validate branch operating hours
    if (branch.opening_time && branch.closing_time) {
      if (createBookingDto.booking_time < branch.opening_time || 
          createBookingDto.booking_time > branch.closing_time) {
        throw new BadRequestException(
          `Chi nhánh chỉ mở cửa từ ${branch.opening_time} đến ${branch.closing_time}`
        );
      }
    }

    // Check for duplicate booking
    const existingBookings = await this.bookingRepository.findByBranchAndDate(
      createBookingDto.branch_id, 
      bookingDate
    );
    
    const duplicateBooking = existingBookings.find(booking => 
      booking.phone_number === createBookingDto.phone_number &&
      booking.booking_time === createBookingDto.booking_time &&
      (booking.status === BookingStatus.PENDING || booking.status === BookingStatus.CONFIRMED)
    );
    
    if (duplicateBooking) {
      throw new ConflictException('Đã có đặt bàn trùng số điện thoại, thời gian và chi nhánh');
    }

    // Validate party size
    if (createBookingDto.party_size > 20) {
      throw new BadRequestException('Đối với nhóm trên 20 người, vui lòng liên hệ trực tiếp với nhà hàng');
    }

    // Create booking with default status and source
    const bookingData = {
      ...createBookingDto,
      booking_date: bookingDate,
      status: BookingStatus.PENDING,
      source: createBookingDto.source || 'phone_ai' as any,
    };

    return await this.bookingRepository.create(bookingData);
  }

  async findAll(): Promise<Booking[]> {
    return await this.bookingRepository.findAll();
  }

  async findOne(id: string): Promise<Booking> {
    const booking = await this.bookingRepository.findById(id);

    if (!booking) {
      throw new NotFoundException(`Không tìm thấy đặt bàn với ID ${id}`);
    }

    return booking;
  }

  async findByRestaurant(restaurantId: string): Promise<Booking[]> {
    await this.restaurantsService.findOne(restaurantId);
    return await this.bookingRepository.findByRestaurantId(restaurantId);
  }

  async findByBranch(branchId: string): Promise<Booking[]> {
    await this.branchesService.findOne(branchId);
    return await this.bookingRepository.findByBranchId(branchId);
  }

  async findByCustomerPhone(phoneNumber: string): Promise<Booking[]> {
    return await this.bookingRepository.findByCustomerPhone(phoneNumber);
  }

  async findByDateRange(startDate: string, endDate: string): Promise<Booking[]> {
    const start = new Date(startDate);
    const end = new Date(endDate);
    
    if (start > end) {
      throw new BadRequestException('Ngày bắt đầu phải trước ngày kết thúc');
    }
    
    return await this.bookingRepository.findByDateRange(start, end);
  }

  async findByBranchAndDate(branchId: string, date: string): Promise<Booking[]> {
    await this.branchesService.findOne(branchId);
    const bookingDate = new Date(date);
    bookingDate.setHours(0, 0, 0, 0);
    return await this.bookingRepository.findByBranchAndDate(branchId, bookingDate);
  }

  async update(id: string, updateBookingDto: UpdateBookingDto): Promise<Booking> {
    const booking = await this.findOne(id);
    
    // Cannot update completed or cancelled bookings
    if (booking.status === BookingStatus.COMPLETED || booking.status === BookingStatus.CANCELLED) {
      throw new BadRequestException('Không thể cập nhật đặt bàn đã hoàn thành hoặc đã hủy');
    }

    // Cannot update booking within 2 hours before booking time
    if (booking.booking_date && booking.booking_time) {
      const [hours, minutes] = booking.booking_time.split(':');
      const bookingDateTime = new Date(booking.booking_date);
      bookingDateTime.setHours(parseInt(hours), parseInt(minutes), 0, 0);
      
      const now = new Date();
      const timeDiff = bookingDateTime.getTime() - now.getTime();
      const hoursDiff = timeDiff / (1000 * 3600);
      
      if (hoursDiff < 2 && hoursDiff > 0) {
        throw new BadRequestException('Không thể thay đổi đặt bàn trong vòng 2 giờ trước giờ hẹn');
      }
    }
    
    const updateData: Partial<Booking> = {};
    
    if (updateBookingDto.customer_name !== undefined) {
      updateData.customer_name = updateBookingDto.customer_name;
    }
    
    if (updateBookingDto.phone_number !== undefined) {
      updateData.phone_number = updateBookingDto.phone_number;
    }
    
    if (updateBookingDto.party_size !== undefined) {
      if (updateBookingDto.party_size > 20) {
        throw new BadRequestException('Đối với nhóm trên 20 người, vui lòng liên hệ trực tiếp với nhà hàng');
      }
      updateData.party_size = updateBookingDto.party_size;
    }
    
    if (updateBookingDto.booking_time !== undefined) {
      // Validate operating hours
      const branch = await this.branchesService.findOne(booking.branch_id);
      if (branch.opening_time && branch.closing_time) {
        if (updateBookingDto.booking_time < branch.opening_time || 
            updateBookingDto.booking_time > branch.closing_time) {
          throw new BadRequestException(
            `Chi nhánh chỉ mở cửa từ ${branch.opening_time} đến ${branch.closing_time}`
          );
        }
      }
      updateData.booking_time = updateBookingDto.booking_time;
    }
    
    if (updateBookingDto.booking_date !== undefined) {
      const bookingDate = new Date(updateBookingDto.booking_date);
      bookingDate.setHours(0, 0, 0, 0);
      
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      
      if (bookingDate < today) {
        throw new BadRequestException('Không thể đặt bàn cho ngày trong quá khứ');
      }
      
      const maxDate = new Date();
      maxDate.setMonth(maxDate.getMonth() + 3);
      maxDate.setHours(0, 0, 0, 0);
      
      if (bookingDate > maxDate) {
        throw new BadRequestException('Chỉ có thể đặt bàn trong vòng 3 tháng tới');
      }
      
      updateData.booking_date = bookingDate;
    }
    
    if (updateBookingDto.note !== undefined) {
      updateData.note = updateBookingDto.note;
    }
    
    if (updateBookingDto.source !== undefined) {
      updateData.source = updateBookingDto.source;
    }
    
    if (updateBookingDto.status !== undefined) {
      const currentStatus = booking.status;
      const newStatus = updateBookingDto.status;
      
      // Define valid status transitions
      const validTransitions: Record<BookingStatus, BookingStatus[]> = {
        [BookingStatus.PENDING]: [BookingStatus.CONFIRMED, BookingStatus.CANCELLED],
        [BookingStatus.CONFIRMED]: [BookingStatus.COMPLETED, BookingStatus.CANCELLED, BookingStatus.NO_SHOW],
        [BookingStatus.CANCELLED]: [],
        [BookingStatus.COMPLETED]: [],
        [BookingStatus.NO_SHOW]: [],
      };
      
      if (!validTransitions[currentStatus]?.includes(newStatus)) {
        throw new BadRequestException(
          `Không thể chuyển từ trạng thái ${currentStatus} sang ${newStatus}`
        );
      }
      
      updateData.status = newStatus;
    }

    if (updateBookingDto.shipper_status !== undefined) {
      updateData.shipper_status = updateBookingDto.shipper_status;
    }
    
    return await this.bookingRepository.update(id, updateData);
  }

  async remove(id: string): Promise<void> {
    await this.findOne(id); // Check if exists
    await this.bookingRepository.delete(id);
  }

  async findByStatus(status: string): Promise<Booking[]> {
    return await this.bookingRepository.findByStatus(status as any);
  }

  async findBySource(source: string): Promise<Booking[]> {
    return await this.bookingRepository.findBySource(source as any);
  }

  async getBookingStats(): Promise<{
    totalBookings: number;
    pendingBookings: number;
    confirmedBookings: number;
    cancelledBookings: number;
  }> {
    const [total, pending, confirmed, cancelled] = await Promise.all([
      this.bookingRepository.count(),
      this.bookingRepository.countByStatus(BookingStatus.PENDING),
      this.bookingRepository.countByStatus(BookingStatus.CONFIRMED),
      this.bookingRepository.countByStatus(BookingStatus.CANCELLED),
    ]);

    return {
      totalBookings: total,
      pendingBookings: pending,
      confirmedBookings: confirmed,
      cancelledBookings: cancelled,
    };
  }

  /**
   * Tạo đặt bàn từ AI voice assistant
   * Flow:
   * 1. AI gọi /restaurants/by-hotline/:hotline → get restaurant_id
   * 2. AI gọi /restaurants/:id/branches → get branches list
   * 3. Khách chọn branch → get branch_id
   * 4. AI gửi booking với restaurant_id + branch_id
   */
  async createFromAI(createAIBookingDto: CreateAIBookingDto): Promise<Booking> {
    // Validate restaurant exists and is active
    const restaurant = await this.restaurantsService.findOne(createAIBookingDto.restaurant_id);
    if (restaurant.status !== RestaurantStatus.ACTIVE) {
      throw new BadRequestException('Nhà hàng hiện không hoạt động');
    }

    // Validate branch exists and is active
    const branch = await this.branchesService.findOne(createAIBookingDto.branch_id);
    if (branch.status !== BranchStatus.ACTIVE) {
      throw new BadRequestException('Chi nhánh hiện không hoạt động');
    }

    // Validate branch belongs to restaurant
    if (branch.restaurant_id !== createAIBookingDto.restaurant_id) {
      throw new BadRequestException('Chi nhánh không thuộc về nhà hàng được chọn');
    }

    // Validate booking date
    const bookingDate = new Date(createAIBookingDto.booking_date);
    bookingDate.setHours(0, 0, 0, 0);
    
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    
    if (bookingDate < today) {
      throw new BadRequestException('Không thể đặt bàn cho ngày trong quá khứ');
    }

    const maxDate = new Date();
    maxDate.setMonth(maxDate.getMonth() + 3);
    maxDate.setHours(0, 0, 0, 0);
    
    if (bookingDate > maxDate) {
      throw new BadRequestException('Chỉ có thể đặt bàn trong vòng 3 tháng tới');
    }

    // Validate branch operating hours
    if (branch.opening_time && branch.closing_time) {
      if (createAIBookingDto.booking_time < branch.opening_time || 
          createAIBookingDto.booking_time > branch.closing_time) {
        throw new BadRequestException(
          `Chi nhánh chỉ mở cửa từ ${branch.opening_time} đến ${branch.closing_time}`
        );
      }
    }

    // Check for duplicate booking
    const existingBookings = await this.bookingRepository.findByBranchAndDate(
      createAIBookingDto.branch_id, 
      bookingDate
    );
    
    const duplicateBooking = existingBookings.find(booking => 
      booking.phone_number === createAIBookingDto.customer_phone &&
      booking.booking_time === createAIBookingDto.booking_time &&
      (booking.status === BookingStatus.PENDING || booking.status === BookingStatus.CONFIRMED)
    );
    
    if (duplicateBooking) {
      throw new ConflictException('Đã có đặt bàn trùng số điện thoại, thời gian và chi nhánh');
    }

    // Validate party size
    if (createAIBookingDto.party_size > 20) {
      throw new BadRequestException('Đối với nhóm trên 20 người, vui lòng liên hệ trực tiếp với nhà hàng');
    }

    // Create booking (source = phone_ai, status = pending by default)
    const bookingData = {
      restaurant_id: createAIBookingDto.restaurant_id,
      branch_id: createAIBookingDto.branch_id,
      customer_name: createAIBookingDto.customer_name,
      phone_number: createAIBookingDto.customer_phone,
      party_size: createAIBookingDto.party_size,
      booking_date: bookingDate,
      booking_time: createAIBookingDto.booking_time,
      note: createAIBookingDto.note || `Đặt bàn qua AI voice`,
      source: BookingSource.PHONE_AI,
      status: BookingStatus.PENDING,
    };

    return await this.bookingRepository.create(bookingData);
  }

  async createFromDto(bookingData: Partial<Booking>): Promise<Booking> {
    // Direct creation for internal use (e.g., from MenuService)
    return await this.bookingRepository.create(bookingData);
  }
}
