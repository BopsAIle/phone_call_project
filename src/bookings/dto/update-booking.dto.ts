import { ApiPropertyOptional } from '@nestjs/swagger';
import { 
  IsOptional, 
  IsString, 
  Length, 
  IsEnum, 
  Matches, 
  IsInt, 
  Min, 
  Max,
  IsDateString
} from 'class-validator';
import { BookingSource, BookingStatus } from '../entities/booking.entity';

export class UpdateBookingDto {
  @ApiPropertyOptional({
    description: 'Tên khách hàng',
    example: 'Nguyễn Thị B',
    maxLength: 255,
  })
  @IsOptional()
  @IsString({ message: 'Tên khách hàng phải là chuỗi' })
  @Length(1, 255, { message: 'Tên khách hàng phải từ 1-255 ký tự' })
  customer_name?: string;

  @ApiPropertyOptional({
    description: 'Số điện thoại khách hàng',
    example: '0987654321',
    maxLength: 20,
  })
  @IsOptional()
  @IsString({ message: 'Số điện thoại phải là chuỗi' })
  @Length(1, 20, { message: 'Số điện thoại phải từ 1-20 ký tự' })
  phone_number?: string;

  @ApiPropertyOptional({
    description: 'Số lượng người',
    example: 6,
    minimum: 1,
    maximum: 50,
  })
  @IsOptional()
  @IsInt({ message: 'Số lượng người phải là số nguyên' })
  @Min(1, { message: 'Số lượng người tối thiểu là 1' })
  @Max(50, { message: 'Số lượng người tối đa là 50' })
  party_size?: number;

  @ApiPropertyOptional({
    description: 'Ngày đặt bàn (YYYY-MM-DD)',
    example: '2024-08-26',
  })
  @IsOptional()
  @IsDateString({}, { message: 'Ngày đặt bàn phải có định dạng YYYY-MM-DD' })
  booking_date?: string;

  @ApiPropertyOptional({
    description: 'Giờ đặt bàn (HH:MM)',
    example: '20:00',
  })
  @IsOptional()
  @IsString({ message: 'Giờ đặt bàn phải là chuỗi' })
  @Matches(/^([01]?[0-9]|2[0-3]):[0-5][0-9]$/, { message: 'Giờ đặt bàn phải có định dạng HH:MM' })
  booking_time?: string;

  @ApiPropertyOptional({
    description: 'Ghi chú đặt bàn',
    example: 'Yêu cầu bàn VIP',
  })
  @IsOptional()
  @IsString({ message: 'Ghi chú phải là chuỗi' })
  note?: string;

  @ApiPropertyOptional({
    description: 'Nguồn đặt bàn',
    example: BookingSource.PHONE_AI,
    enum: BookingSource,
  })
  @IsOptional()
  @IsEnum(BookingSource, { message: 'Nguồn đặt bàn không hợp lệ' })
  source?: BookingSource;

  @ApiPropertyOptional({
    description: 'Trạng thái đặt bàn',
    example: BookingStatus.CONFIRMED,
    enum: BookingStatus,
  })
  @IsOptional()
  @IsEnum(BookingStatus, { message: 'Trạng thái đặt bàn không hợp lệ' })
  status?: BookingStatus;
}