import { ApiPropertyOptional } from '@nestjs/swagger';
import { IsOptional, IsString, Length, IsEnum } from 'class-validator';
import { RestaurantStatus } from '../entities/restaurant.entity';

export class UpdateRestaurantDto {
  @ApiPropertyOptional({
    description: 'Tên nhà hàng',
    example: 'Nhà hàng XYZ',
    maxLength: 255,
  })
  @IsOptional()
  @IsString({ message: 'Tên nhà hàng phải là chuỗi' })
  @Length(1, 255, { message: 'Tên nhà hàng phải từ 1-255 ký tự' })
  name?: string;

  @ApiPropertyOptional({
    description: 'Số điện thoại nhà hàng',
    example: '0987654321',
    maxLength: 20,
  })
  @IsOptional()
  @IsString({ message: 'Số điện thoại phải là chuỗi' })
  @Length(1, 20, { message: 'Số điện thoại phải từ 1-20 ký tự' })
  phone?: string;

  @ApiPropertyOptional({
    description: 'Trạng thái nhà hàng',
    example: RestaurantStatus.INACTIVE,
    enum: RestaurantStatus,
  })
  @IsOptional()
  @IsEnum(RestaurantStatus, { message: 'Trạng thái chỉ có thể là active hoặc inactive' })
  status?: RestaurantStatus;
}