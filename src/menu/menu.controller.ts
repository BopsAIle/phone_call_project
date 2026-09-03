import {
  Controller,
  Get,
  Post,
  Body,
  Param,
  Patch,
  Delete,
  HttpCode,
  HttpStatus,
} from '@nestjs/common';
import {
  ApiTags,
  ApiOperation,
  ApiResponse,
  ApiParam,
  ApiBody,
} from '@nestjs/swagger';
import { MenuService } from './menu.service';
import { MenuItem } from './entities/menu-item.entity';
import { OrderItem } from './entities/order-item.entity';
import { CreateMenuItemDto } from './dto/create-menu-item.dto';
import { CreateTakeoutBookingDto } from './dto/create-takeout-booking.dto';
import { CreateDeliveryBookingDto } from './dto/create-delivery-booking.dto';
import { Booking } from '../bookings/entities/booking.entity';

@ApiTags('Menu & Đặt Hàng Mang Về')
@Controller('menu')
export class MenuController {
  constructor(private readonly menuService: MenuService) {}

  // ===== QUẢN LÝ MENU =====

  @Post()
  @ApiOperation({ summary: 'Tạo menu item mới' })
  @ApiBody({ type: CreateMenuItemDto })
  @ApiResponse({
    status: 201,
    description: 'Tạo menu item thành công',
    type: MenuItem,
  })
  @ApiResponse({
    status: 404,
    description: 'Chi nhánh không được tìm thấy',
  })
  async createMenuItem(@Body() createMenuItemDto: CreateMenuItemDto): Promise<MenuItem> {
    return await this.menuService.createMenuItem(createMenuItemDto);
  }

  @Get('branch/:branchId')
  @ApiOperation({
    summary: 'Lấy danh sách menu item của chi nhánh',
    description: 'Sử dụng cho AI voice để gợi ý menu cho khách',
  })
  @ApiParam({
    name: 'branchId',
    description: 'ID của chi nhánh',
    example: '223e4567-e89b-12d3-a456-426614174000',
  })
  @ApiResponse({
    status: 200,
    description: 'Danh sách menu items',
    type: [MenuItem],
  })
  @ApiResponse({
    status: 404,
    description: 'Chi nhánh không được tìm thấy',
  })
  async getMenuByBranchId(@Param('branchId') branchId: string): Promise<MenuItem[]> {
    return await this.menuService.getMenuByBranchId(branchId);
  }

  @Get(':id')
  @ApiOperation({ summary: 'Lấy chi tiết menu item' })
  @ApiParam({
    name: 'id',
    description: 'ID của menu item',
    example: '323e4567-e89b-12d3-a456-426614174000',
  })
  @ApiResponse({
    status: 200,
    description: 'Chi tiết menu item',
    type: MenuItem,
  })
  @ApiResponse({
    status: 404,
    description: 'Menu item không được tìm thấy',
  })
  async getMenuItem(@Param('id') id: string): Promise<MenuItem> {
    return await this.menuService.getMenuItem(id);
  }

  @Patch(':id')
  @ApiOperation({ summary: 'Cập nhật menu item' })
  @ApiParam({
    name: 'id',
    description: 'ID của menu item',
    example: '323e4567-e89b-12d3-a456-426614174000',
  })
  @ApiBody({ type: CreateMenuItemDto })
  @ApiResponse({
    status: 200,
    description: 'Cập nhật menu item thành công',
    type: MenuItem,
  })
  @ApiResponse({
    status: 404,
    description: 'Menu item không được tìm thấy',
  })
  async updateMenuItem(
    @Param('id') id: string,
    @Body() updateData: Partial<CreateMenuItemDto>,
  ): Promise<MenuItem | null> {
    return await this.menuService.updateMenuItem(id, updateData as any);
  }

  @Delete(':id')
  @HttpCode(HttpStatus.NO_CONTENT)
  @ApiOperation({ summary: 'Xóa menu item' })
  @ApiParam({
    name: 'id',
    description: 'ID của menu item',
    example: '323e4567-e89b-12d3-a456-426614174000',
  })
  @ApiResponse({
    status: 204,
    description: 'Xóa menu item thành công',
  })
  @ApiResponse({
    status: 404,
    description: 'Menu item không được tìm thấy',
  })
  async deleteMenuItem(@Param('id') id: string): Promise<void> {
    return await this.menuService.deleteMenuItem(id);
  }

  // ===== ĐẶT HÀNG MANG VỀ =====

  @Post('takeout/ai')
  @ApiOperation({
    summary: 'Tạo đơn mang về từ AI voice assistant',
    description:
      'Endpoint dành cho AI voice - khách gọi lễ tân AI để đặt đồ ăn mang về',
  })
  @ApiBody({ type: CreateTakeoutBookingDto })
  @ApiResponse({
    status: 201,
    description: 'Tạo đơn mang về thành công',
  })
  @ApiResponse({
    status: 400,
    description: 'Dữ liệu không hợp lệ hoặc chi nhánh không hoạt động',
  })
  @ApiResponse({
    status: 404,
    description: 'Không tìm thấy nhà hàng, chi nhánh hoặc menu items',
  })
  async createTakeoutBooking(
    @Body() createTakeoutBookingDto: CreateTakeoutBookingDto,
  ): Promise<any> {
    return await this.menuService.createTakeoutBooking(createTakeoutBookingDto);
  }

  @Get('order/:bookingId/items')
  @ApiOperation({ summary: 'Lấy chi tiết items của đơn hàng' })
  @ApiParam({
    name: 'bookingId',
    description: 'ID của booking',
    example: '423e4567-e89b-12d3-a456-426614174000',
  })
  @ApiResponse({
    status: 200,
    description: 'Danh sách order items',
    type: [OrderItem],
  })
  async getOrderItems(@Param('bookingId') bookingId: string): Promise<OrderItem[]> {
    return await this.menuService.getOrderItems(bookingId);
  }

  @Patch('takeout/:bookingId/confirm')
  @ApiOperation({
    summary: 'Xác nhận đơn mang về (trừ kho)',
    description: 'Khi xác nhận, sẽ cập nhật status=CONFIRMED và trừ quantity_available của các items',
  })
  @ApiParam({
    name: 'bookingId',
    description: 'ID của booking',
    example: '423e4567-e89b-12d3-a456-426614174000',
  })
  @ApiResponse({
    status: 200,
    description: 'Xác nhận đơn thành công',
  })
  @ApiResponse({
    status: 404,
    description: 'Không tìm thấy booking',
  })
  @ApiResponse({
    status: 400,
    description: 'Không thể xác nhận booking này',
  })
  async confirmTakeoutBooking(@Param('bookingId') bookingId: string): Promise<any> {
    return await this.menuService.confirmTakeoutBooking(bookingId);
  }

  // ===== ĐẶT HÀNG GIAO HÀNG =====

  @Post('delivery/ai')
  @ApiOperation({
    summary: 'Tạo đơn giao hàng từ AI voice assistant',
    description:
      'Endpoint dành cho AI voice - khách gọi lễ tân AI để đặt đồ ăn giao hàng',
  })
  @ApiBody({ type: CreateDeliveryBookingDto })
  @ApiResponse({
    status: 201,
    description: 'Tạo đơn giao hàng thành công',
  })
  @ApiResponse({
    status: 400,
    description: 'Dữ liệu không hợp lệ hoặc chi nhánh không hoạt động',
  })
  @ApiResponse({
    status: 404,
    description: 'Không tìm thấy nhà hàng, chi nhánh hoặc menu items',
  })
  async createDeliveryBooking(
    @Body() createDeliveryBookingDto: CreateDeliveryBookingDto,
  ): Promise<any> {
    return await this.menuService.createDeliveryBooking(createDeliveryBookingDto);
  }

  @Patch('delivery/:bookingId/confirm')
  @ApiOperation({
    summary: 'Xác nhận đơn giao hàng (trừ kho)',
    description: 'Khi xác nhận, sẽ cập nhật status=CONFIRMED, shipper_status=ASSIGNED và trừ quantity_available của các items',
  })
  @ApiParam({
    name: 'bookingId',
    description: 'ID của booking',
    example: '423e4567-e89b-12d3-a456-426614174000',
  })
  @ApiResponse({
    status: 200,
    description: 'Xác nhận đơn thành công',
  })
  @ApiResponse({
    status: 404,
    description: 'Không tìm thấy booking',
  })
  @ApiResponse({
    status: 400,
    description: 'Không thể xác nhận booking này',
  })
  async confirmDeliveryBooking(@Param('bookingId') bookingId: string): Promise<any> {
    return await this.menuService.confirmDeliveryBooking(bookingId);
  }
}
