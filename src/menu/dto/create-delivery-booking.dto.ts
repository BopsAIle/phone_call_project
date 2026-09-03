import { ApiProperty } from '@nestjs/swagger';
import {
  IsNotEmpty,
  IsString,
  Length,
  IsOptional,
  IsUUID,
  Matches,
  IsArray,
  ValidateNested,
  IsInt,
  Min,
  IsDateString,
  IsDecimal,
  MinLength,
} from 'class-validator';
import { Type } from 'class-transformer';

class OrderItemDto {
  @ApiProperty({
    description: 'ID của menu item',
    example: '323e4567-e89b-12d3-a456-426614174000',
  })
  @IsNotEmpty({ message: 'ID menu item không được để trống' })
  @IsUUID('4', { message: 'ID menu item phải là UUID hợp lệ' })
  menu_item_id: string;

  @ApiProperty({
    description: 'Số lượng',
    example: 2,
    minimum: 1,
  })
  @IsNotEmpty({ message: 'Số lượng không được để trống' })
  @IsInt({ message: 'Số lượng phải là số nguyên' })
  @Min(1, { message: 'Số lượng tối thiểu là 1' })
  quantity: number;
}

/**
 * DTO cho AI voice assistant tạo đơn giao hàng (delivery)
 * Flow:
 * 1. AI gọi GET /menu/branch/:branchId để lấy danh sách menu
 * 2. Khách chọn món, AI gửi delivery booking
 */
export class CreateDeliveryBookingDto {
  @ApiProperty({
    description: 'ID của nhà hàng',
    example: '123e4567-e89b-12d3-a456-426614174000',
  })
  @IsNotEmpty({ message: 'ID nhà hàng không được để trống' })
  @IsUUID('4', { message: 'ID nhà hàng phải là UUID hợp lệ' })
  restaurant_id: string;

  @ApiProperty({
    description: 'ID của chi nhánh',
    example: '223e4567-e89b-12d3-a456-426614174000',
  })
  @IsNotEmpty({ message: 'ID chi nhánh không được để trống' })
  @IsUUID('4', { message: 'ID chi nhánh phải là UUID hợp lệ' })
  branch_id: string;

  @ApiProperty({
    description: 'Tên khách hàng',
    example: 'Nguyễn Văn A',
    maxLength: 255,
  })
  @IsNotEmpty({ message: 'Tên khách hàng không được để trống' })
  @IsString({ message: 'Tên khách hàng phải là chuỗi' })
  @Length(1, 255, { message: 'Tên khách hàng phải từ 1-255 ký tự' })
  customer_name: string;

  @ApiProperty({
    description: 'Số điện thoại khách hàng',
    example: '0123456789',
    maxLength: 20,
  })
  @IsNotEmpty({ message: 'Số điện thoại khách hàng không được để trống' })
  @IsString({ message: 'Số điện thoại phải là chuỗi' })
  @Length(1, 20, { message: 'Số điện thoại phải từ 1-20 ký tự' })
  customer_phone: string;

  @ApiProperty({
    description: 'Ngày giao hàng (YYYY-MM-DD)',
    example: '2024-08-25',
  })
  @IsNotEmpty({ message: 'Ngày giao hàng không được để trống' })
  @IsDateString({}, { message: 'Ngày giao hàng phải có định dạng YYYY-MM-DD' })
  booking_date: string;

  @ApiProperty({
    description: 'Giờ nhận hàng (HH:MM)',
    example: '12:30',
  })
  @IsNotEmpty({ message: 'Giờ nhận hàng không được để trống' })
  @IsString({ message: 'Giờ nhận hàng phải là chuỗi' })
  @Matches(/^([01]?[0-9]|2[0-3]):[0-5][0-9]$/, {
    message: 'Giờ nhận hàng phải có định dạng HH:MM',
  })
  booking_time: string;

  @ApiProperty({
    description: 'Danh sách các items trong đơn hàng',
    type: [OrderItemDto],
  })
  @IsNotEmpty({ message: 'Danh sách items không được để trống' })
  @IsArray({ message: 'Items phải là một mảng' })
  @ValidateNested({ each: true })
  @Type(() => OrderItemDto)
  items: OrderItemDto[];

  // Delivery specific fields
  @ApiProperty({
    description: 'Địa chỉ giao hàng',
    example: '123 Đường Láng, Đống Đa, Hà Nội',
    maxLength: 500,
  })
  @IsNotEmpty({ message: 'Địa chỉ giao hàng không được để trống' })
  @IsString({ message: 'Địa chỉ giao hàng phải là chuỗi' })
  @Length(5, 500, { message: 'Địa chỉ giao hàng phải từ 5-500 ký tự' })
  delivery_address: string;

  @ApiProperty({
    description: 'Số điện thoại người nhận (nếu khác)',
    example: '0987654321',
    maxLength: 20,
    required: false,
  })
  @IsOptional()
  @IsString({ message: 'Số điện thoại người nhận phải là chuỗi' })
  @Length(1, 20, { message: 'Số điện thoại phải từ 1-20 ký tự' })
  delivery_phone?: string;

  @ApiProperty({
    description: 'Phí giao hàng',
    example: 25000,
    minimum: 0,
  })
  @IsNotEmpty({ message: 'Phí giao hàng không được để trống' })
  @Type(() => Number)
  @Min(0, { message: 'Phí giao hàng phải >= 0' })
  delivery_fee: number;

  @ApiProperty({
    description: 'Thời gian giao dự kiến (HH:MM)',
    example: '14:30',
  })
  @IsNotEmpty({ message: 'Thời gian giao dự kiến không được để trống' })
  @IsString({ message: 'Thời gian giao phải là chuỗi' })
  @Matches(/^([01]?[0-9]|2[0-3]):[0-5][0-9]$/, {
    message: 'Thời gian giao phải có định dạng HH:MM',
  })
  estimated_delivery_time: string;

  @ApiProperty({
    description: 'Ghi chú đặt hàng từ AI',
    example: 'Không ớt, thêm cơm chiên',
    required: false,
  })
  @IsOptional()
  @IsString({ message: 'Ghi chú phải là chuỗi' })
  note?: string;
}
