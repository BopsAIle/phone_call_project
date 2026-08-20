import {
  Controller,
  Get,
  Post,
  Body,
  Patch,
  Param,
  Delete,
  Query,
} from '@nestjs/common';
import {
  ApiTags,
  ApiOperation,
  ApiResponse,
  ApiParam,
  ApiBody,
  ApiQuery,
} from '@nestjs/swagger';
import { BookingsService } from './bookings.service';
import { CreateBookingDto } from './dto/create-booking.dto';
import { CreateAIBookingDto } from './dto/create-ai-booking.dto';
import { UpdateBookingDto } from './dto/update-booking.dto';
import { Booking, BookingStatus, BookingSource } from './entities/booking.entity';

@ApiTags('Bookings')
@Controller('bookings')
export class BookingsController {
  constructor(private readonly bookingsService: BookingsService) {}

  @Post()
  @ApiOperation({ summary: 'Tạo đặt bàn mới' })
  @ApiBody({ type: CreateBookingDto })
  @ApiResponse({
    status: 201,
    description: 'Tạo đặt bàn thành công',
    type: Booking,
  })
  @ApiResponse({
    status: 400,
    description: 'Dữ liệu không hợp lệ hoặc chi nhánh không thuộc nhà hàng',
  })
  @ApiResponse({
    status: 404,
    description: 'Không tìm thấy nhà hàng hoặc chi nhánh',
  })
  async create(@Body() createBookingDto: CreateBookingDto): Promise<Booking> {
    return await this.bookingsService.create(createBookingDto);
  }

  @Post('ai')
  @ApiOperation({
    summary: 'Tạo đặt bàn từ AI voice assistant',
    description: 'Endpoint dành cho AI voice - chỉ cần gửi số điện thoại chi nhánh, AI sẽ được mapped tới chi nhánh đó',
  })
  @ApiBody({ type: CreateAIBookingDto })
  @ApiResponse({
    status: 201,
    description: 'Tạo đặt bàn thành công',
    type: Booking,
  })
  @ApiResponse({
    status: 400,
    description: 'Dữ liệu không hợp lệ hoặc chi nhánh không hoạt động',
  })
  @ApiResponse({
    status: 404,
    description: 'Không tìm thấy chi nhánh với số điện thoại',
  })
  async createFromAI(@Body() createAIBookingDto: CreateAIBookingDto): Promise<Booking> {
    return await this.bookingsService.createFromAI(createAIBookingDto);
  }

  @Get()
  @ApiOperation({ summary: 'Lấy danh sách tất cả đặt bàn' })
  @ApiQuery({
    name: 'status',
    required: false,
    enum: BookingStatus,
    description: 'Lọc theo trạng thái',
  })
  @ApiQuery({
    name: 'source',
    required: false,
    enum: BookingSource,
    description: 'Lọc theo nguồn đặt bàn',
  })
  @ApiQuery({
    name: 'restaurant_id',
    required: false,
    description: 'Lọc theo ID nhà hàng',
  })
  @ApiQuery({
    name: 'branch_id',
    required: false,
    description: 'Lọc theo ID chi nhánh',
  })
  @ApiQuery({
    name: 'phone_number',
    required: false,
    description: 'Lọc theo số điện thoại khách hàng',
  })
  @ApiQuery({
    name: 'start_date',
    required: false,
    description: 'Ngày bắt đầu (YYYY-MM-DD)',
  })
  @ApiQuery({
    name: 'end_date',
    required: false,
    description: 'Ngày kết thúc (YYYY-MM-DD)',
  })
  @ApiResponse({
    status: 200,
    description: 'Danh sách đặt bàn',
    type: [Booking],
  })
  async findAll(
    @Query('status') status?: BookingStatus,
    @Query('source') source?: BookingSource,
    @Query('restaurant_id') restaurantId?: string,
    @Query('branch_id') branchId?: string,
    @Query('phone_number') phoneNumber?: string,
    @Query('start_date') startDate?: string,
    @Query('end_date') endDate?: string,
  ): Promise<Booking[]> {
    if (restaurantId) {
      return await this.bookingsService.findByRestaurant(restaurantId);
    }
    if (branchId) {
      return await this.bookingsService.findByBranch(branchId);
    }
    if (phoneNumber) {
      return await this.bookingsService.findByCustomerPhone(phoneNumber);
    }
    if (startDate && endDate) {
      return await this.bookingsService.findByDateRange(startDate, endDate);
    }
    if (status) {
      return await this.bookingsService.findByStatus(status);
    }
    if (source) {
      return await this.bookingsService.findBySource(source);
    }
    return await this.bookingsService.findAll();
  }

  @Get('stats')
  @ApiOperation({ summary: 'Lấy thống kê đặt bàn' })
  @ApiResponse({
    status: 200,
    description: 'Thống kê đặt bàn',
    schema: {
      type: 'object',
      properties: {
        totalBookings: { type: 'number', example: 150 },
        pendingBookings: { type: 'number', example: 25 },
        confirmedBookings: { type: 'number', example: 100 },
        cancelledBookings: { type: 'number', example: 25 },
      },
    },
  })
  async getStats(): Promise<{
    totalBookings: number;
    pendingBookings: number;
    confirmedBookings: number;
    cancelledBookings: number;
  }> {
    return await this.bookingsService.getBookingStats();
  }

  @Get('branch/:branchId/date/:date')
  @ApiOperation({ summary: 'Lấy đặt bàn theo chi nhánh và ngày' })
  @ApiParam({
    name: 'branchId',
    description: 'UUID của chi nhánh',
    example: '123e4567-e89b-12d3-a456-426614174000',
  })
  @ApiParam({
    name: 'date',
    description: 'Ngày (YYYY-MM-DD)',
    example: '2024-08-25',
  })
  @ApiResponse({
    status: 200,
    description: 'Danh sách đặt bàn theo chi nhánh và ngày',
    type: [Booking],
  })
  async findByBranchAndDate(
    @Param('branchId') branchId: string,
    @Param('date') date: string,
  ): Promise<Booking[]> {
    return await this.bookingsService.findByBranchAndDate(branchId, date);
  }

  @Get(':id')
  @ApiOperation({ summary: 'Lấy thông tin đặt bàn theo ID' })
  @ApiParam({
    name: 'id',
    description: 'UUID của đặt bàn',
    example: '123e4567-e89b-12d3-a456-426614174000',
  })
  @ApiResponse({
    status: 200,
    description: 'Thông tin đặt bàn',
    type: Booking,
  })
  @ApiResponse({
    status: 404,
    description: 'Không tìm thấy đặt bàn',
  })
  async findOne(@Param('id') id: string): Promise<Booking> {
    return await this.bookingsService.findOne(id);
  }

  @Patch(':id')
  @ApiOperation({ summary: 'Cập nhật thông tin đặt bàn' })
  @ApiParam({
    name: 'id',
    description: 'UUID của đặt bàn',
    example: '123e4567-e89b-12d3-a456-426614174000',
  })
  @ApiBody({ type: UpdateBookingDto })
  @ApiResponse({
    status: 200,
    description: 'Cập nhật đặt bàn thành công',
    type: Booking,
  })
  @ApiResponse({
    status: 404,
    description: 'Không tìm thấy đặt bàn',
  })
  @ApiResponse({
    status: 400,
    description: 'Dữ liệu không hợp lệ',
  })
  async update(
    @Param('id') id: string,
    @Body() updateBookingDto: UpdateBookingDto,
  ): Promise<Booking> {
    return await this.bookingsService.update(id, updateBookingDto);
  }

  @Delete(':id')
  @ApiOperation({ summary: 'Xóa đặt bàn' })
  @ApiParam({
    name: 'id',
    description: 'UUID của đặt bàn',
    example: '123e4567-e89b-12d3-a456-426614174000',
  })
  @ApiResponse({
    status: 200,
    description: 'Xóa đặt bàn thành công',
  })
  @ApiResponse({
    status: 404,
    description: 'Không tìm thấy đặt bàn',
  })
  async remove(@Param('id') id: string): Promise<{ message: string }> {
    await this.bookingsService.remove(id);
    return { message: 'Xóa đặt bàn thành công' };
  }
}