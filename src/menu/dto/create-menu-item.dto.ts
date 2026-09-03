import { ApiProperty } from '@nestjs/swagger';
import {
  IsNotEmpty,
  IsString,
  IsNumber,
  IsUUID,
  Length,
  IsOptional,
  Min,
  Max,
  IsEnum,
} from 'class-validator';
import { MenuItemStatus } from '../entities/menu-item.entity';

export class CreateMenuItemDto {
  @ApiProperty({
    description: 'ID của chi nhánh',
    example: '223e4567-e89b-12d3-a456-426614174000',
  })
  @IsNotEmpty({ message: 'ID chi nhánh không được để trống' })
  @IsUUID('4', { message: 'ID chi nhánh phải là UUID hợp lệ' })
  branch_id: string;

  @ApiProperty({
    description: 'Tên món ăn',
    example: 'Phở bò',
    maxLength: 255,
  })
  @IsNotEmpty({ message: 'Tên món ăn không được để trống' })
  @IsString({ message: 'Tên món ăn phải là chuỗi' })
  @Length(1, 255, { message: 'Tên món ăn phải từ 1-255 ký tự' })
  name: string;

  @ApiProperty({
    description: 'Mô tả món ăn',
    example: 'Phở bò tươi, nước dùng thơm ngon',
    required: false,
  })
  @IsOptional()
  @IsString({ message: 'Mô tả phải là chuỗi' })
  description?: string;

  @ApiProperty({
    description: 'Giá tiền (VNĐ)',
    example: 45000,
    minimum: 0,
  })
  @IsNotEmpty({ message: 'Giá tiền không được để trống' })
  @IsNumber({}, { message: 'Giá tiền phải là số' })
  @Min(0, { message: 'Giá tiền phải lớn hơn hoặc bằng 0' })
  price: number;

  @ApiProperty({
    description: 'Trạng thái món ăn',
    enum: MenuItemStatus,
    default: MenuItemStatus.AVAILABLE,
    required: false,
  })
  @IsOptional()
  @IsEnum(MenuItemStatus)
  status?: MenuItemStatus;

  @ApiProperty({
    description: 'Số lượng có sẵn',
    example: 100,
    minimum: 0,
    required: false,
  })
  @IsOptional()
  @IsNumber({}, { message: 'Số lượng phải là số' })
  @Min(0, { message: 'Số lượng phải lớn hơn hoặc bằng 0' })
  quantity_available?: number;
}
