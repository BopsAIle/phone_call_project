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
 * DTO cho AI voice assistant tạo đơn mang về (takeout)
 * Flow:
 * 1. AI gọi GET /menu/branch/:branchId để lấy danh sách menu
 * 2. Khách chọn món, AI gửi takeout booking
 */
export class CreateTakeoutBookingDto {
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
    description: 'Ngày lấy đồ (YYYY-MM-DD)',
    example: '2024-08-25',
  })
  @IsNotEmpty({ message: 'Ngày lấy đồ không được để trống' })
  @IsDateString({}, { message: 'Ngày lấy đồ phải có định dạng YYYY-MM-DD' })
  booking_date: string;

  @ApiProperty({
    description: 'Giờ lấy đồ (HH:MM)',
    example: '12:30',
  })
  @IsNotEmpty({ message: 'Giờ lấy đồ không được để trống' })
  @IsString({ message: 'Giờ lấy đồ phải là chuỗi' })
  @Matches(/^([01]?[0-9]|2[0-3]):[0-5][0-9]$/, {
    message: 'Giờ lấy đồ phải có định dạng HH:MM',
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

  @ApiProperty({
    description: 'Ghi chú đặt hàng từ AI',
    example: 'Không ớt, thêm cơm chiên',
    required: false,
  })
  @IsOptional()
  @IsString({ message: 'Ghi chú phải là chuỗi' })
  note?: string;
}
