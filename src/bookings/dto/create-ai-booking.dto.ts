import { ApiProperty } from '@nestjs/swagger';
import {
  IsNotEmpty,
  IsString,
  Length,
  IsOptional,
  IsUUID,
  Matches,
  IsInt,
  Min,
  Max,
  IsDateString,
} from 'class-validator';

/**
 * DTO cho AI voice assistant tạo đặt bàn
 * Flow:
 * 1. AI gọi GET /restaurants/by-hotline/:hotline để lấy restaurant_id
 * 2. AI gọi GET /restaurants/:id/branches để lấy danh sách branches
 * 3. Khách chọn branch, AI gửi booking với restaurant_id + branch_id
 */
export class CreateAIBookingDto {
  @ApiProperty({
    description: 'ID của nhà hàng (lấy từ API /restaurants/by-hotline)',
    example: '123e4567-e89b-12d3-a456-426614174000',
  })
  @IsNotEmpty({ message: 'ID nhà hàng không được để trống' })
  @IsUUID('4', { message: 'ID nhà hàng phải là UUID hợp lệ' })
  restaurant_id: string;

  @ApiProperty({
    description: 'ID của chi nhánh (lấy từ API /restaurants/:id/branches)',
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
    description: 'Số lượng người',
    example: 4,
    minimum: 1,
    maximum: 50,
  })
  @IsNotEmpty({ message: 'Số lượng người không được để trống' })
  @IsInt({ message: 'Số lượng người phải là số nguyên' })
  @Min(1, { message: 'Số lượng người tối thiểu là 1' })
  @Max(50, { message: 'Số lượng người tối đa là 50' })
  party_size: number;

  @ApiProperty({
    description: 'Ngày đặt bàn (YYYY-MM-DD)',
    example: '2024-08-25',
  })
  @IsNotEmpty({ message: 'Ngày đặt bàn không được để trống' })
  @IsDateString({}, { message: 'Ngày đặt bàn phải có định dạng YYYY-MM-DD' })
  booking_date: string;

  @ApiProperty({
    description: 'Giờ đặt bàn (HH:MM)',
    example: '19:30',
  })
  @IsNotEmpty({ message: 'Giờ đặt bàn không được để trống' })
  @IsString({ message: 'Giờ đặt bàn phải là chuỗi' })
  @Matches(/^([01]?[0-9]|2[0-3]):[0-5][0-9]$/, {
    message: 'Giờ đặt bàn phải có định dạng HH:MM',
  })
  booking_time: string;

  @ApiProperty({
    description: 'Ghi chú đặt bàn từ AI',
    example: 'Khách nói muốn bàn gần cửa sổ, không ăn cay',
    required: false,
  })
  @IsOptional()
  @IsString({ message: 'Ghi chú phải là chuỗi' })
  note?: string;
}
