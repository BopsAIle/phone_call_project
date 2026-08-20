import { ApiProperty } from '@nestjs/swagger';
import { IsNotEmpty, IsString, Length, IsOptional, IsEnum } from 'class-validator';
import { RestaurantStatus } from '../entities/restaurant.entity';

export class CreateRestaurantDto {
  @ApiProperty({
    description: 'Tên nhà hàng',
    example: 'Nhà hàng ABC',
    maxLength: 255,
  })
  @IsNotEmpty({ message: 'Tên nhà hàng không được để trống' })
  @IsString({ message: 'Tên nhà hàng phải là chuỗi' })
  @Length(1, 255, { message: 'Tên nhà hàng phải từ 1-255 ký tự' })
  name: string;

  @ApiProperty({
    description: 'Số điện thoại nhà hàng',
    example: '0123456789',
    required: false,
    maxLength: 20,
  })
  @IsOptional()
  @IsString({ message: 'Số điện thoại phải là chuỗi' })
  @Length(1, 20, { message: 'Số điện thoại phải từ 1-20 ký tự' })
  phone?: string;

  @ApiProperty({
    description: 'Trạng thái nhà hàng',
    example: RestaurantStatus.ACTIVE,
    enum: RestaurantStatus,
    required: false,
  })
  @IsOptional()
  @IsEnum(RestaurantStatus, { message: 'Trạng thái chỉ có thể là active hoặc inactive' })
  status?: RestaurantStatus;
}