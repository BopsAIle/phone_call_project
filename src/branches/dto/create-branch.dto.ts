import { ApiProperty } from '@nestjs/swagger';
import { IsNotEmpty, IsString, Length, IsOptional, IsEnum, IsUUID, Matches } from 'class-validator';
import { BranchStatus } from '../entities/branch.entity';

export class CreateBranchDto {
  @ApiProperty({
    description: 'ID của nhà hàng',
    example: '123e4567-e89b-12d3-a456-426614174000',
  })
  @IsNotEmpty({ message: 'ID nhà hàng không được để trống' })
  @IsUUID('4', { message: 'ID nhà hàng phải là UUID hợp lệ' })
  restaurant_id: string;

  @ApiProperty({
    description: 'Tên chi nhánh',
    example: 'Chi nhánh Quận 1',
    maxLength: 255,
  })
  @IsNotEmpty({ message: 'Tên chi nhánh không được để trống' })
  @IsString({ message: 'Tên chi nhánh phải là chuỗi' })
  @Length(1, 255, { message: 'Tên chi nhánh phải từ 1-255 ký tự' })
  name: string;

  @ApiProperty({
    description: 'Địa chỉ chi nhánh',
    example: '123 Nguyễn Huệ, Quận 1, TP.HCM',
    required: false,
  })
  @IsOptional()
  @IsString({ message: 'Địa chỉ phải là chuỗi' })
  address?: string;

  @ApiProperty({
    description: 'Số điện thoại chi nhánh',
    example: '0123456789',
    required: false,
    maxLength: 20,
  })
  @IsOptional()
  @IsString({ message: 'Số điện thoại phải là chuỗi' })
  @Length(1, 20, { message: 'Số điện thoại phải từ 1-20 ký tự' })
  phone?: string;

  @ApiProperty({
    description: 'Giờ mở cửa (HH:MM)',
    example: '08:00',
    required: false,
  })
  @IsOptional()
  @IsString({ message: 'Giờ mở cửa phải là chuỗi' })
  @Matches(/^([01]?[0-9]|2[0-3]):[0-5][0-9]$/, { message: 'Giờ mở cửa phải có định dạng HH:MM' })
  opening_time?: string;

  @ApiProperty({
    description: 'Giờ đóng cửa (HH:MM)',
    example: '22:00',
    required: false,
  })
  @IsOptional()
  @IsString({ message: 'Giờ đóng cửa phải là chuỗi' })
  @Matches(/^([01]?[0-9]|2[0-3]):[0-5][0-9]$/, { message: 'Giờ đóng cửa phải có định dạng HH:MM' })
  closing_time?: string;

  @ApiProperty({
    description: 'Trạng thái chi nhánh',
    example: BranchStatus.ACTIVE,
    enum: BranchStatus,
    required: false,
  })
  @IsOptional()
  @IsEnum(BranchStatus, { message: 'Trạng thái phải là active, inactive hoặc maintenance' })
  status?: BranchStatus;
}