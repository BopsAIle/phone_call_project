import { ApiPropertyOptional } from '@nestjs/swagger';
import { IsOptional, IsString, Length, IsEnum, Matches } from 'class-validator';
import { BranchStatus } from '../entities/branch.entity';

export class UpdateBranchDto {
  @ApiPropertyOptional({
    description: 'Tên chi nhánh',
    example: 'Chi nhánh Quận 2',
    maxLength: 255,
  })
  @IsOptional()
  @IsString({ message: 'Tên chi nhánh phải là chuỗi' })
  @Length(1, 255, { message: 'Tên chi nhánh phải từ 1-255 ký tự' })
  name?: string;

  @ApiPropertyOptional({
    description: 'Địa chỉ chi nhánh',
    example: '456 Hai Bà Trưng, Quận 3, TP.HCM',
  })
  @IsOptional()
  @IsString({ message: 'Địa chỉ phải là chuỗi' })
  address?: string;

  @ApiPropertyOptional({
    description: 'Số điện thoại chi nhánh',
    example: '0987654321',
    maxLength: 20,
  })
  @IsOptional()
  @IsString({ message: 'Số điện thoại phải là chuỗi' })
  @Length(1, 20, { message: 'Số điện thoại phải từ 1-20 ký tự' })
  phone?: string;

  @ApiPropertyOptional({
    description: 'Giờ mở cửa (HH:MM)',
    example: '07:30',
  })
  @IsOptional()
  @IsString({ message: 'Giờ mở cửa phải là chuỗi' })
  @Matches(/^([01]?[0-9]|2[0-3]):[0-5][0-9]$/, { message: 'Giờ mở cửa phải có định dạng HH:MM' })
  opening_time?: string;

  @ApiPropertyOptional({
    description: 'Giờ đóng cửa (HH:MM)',
    example: '23:00',
  })
  @IsOptional()
  @IsString({ message: 'Giờ đóng cửa phải là chuỗi' })
  @Matches(/^([01]?[0-9]|2[0-3]):[0-5][0-9]$/, { message: 'Giờ đóng cửa phải có định dạng HH:MM' })
  closing_time?: string;

  @ApiPropertyOptional({
    description: 'Trạng thái chi nhánh',
    example: BranchStatus.MAINTENANCE,
    enum: BranchStatus,
  })
  @IsOptional()
  @IsEnum(BranchStatus, { message: 'Trạng thái phải là active, inactive hoặc maintenance' })
  status?: BranchStatus;
}