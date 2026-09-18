import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import {
  IsNotEmpty,
  IsOptional,
  IsString,
  IsUUID,
  IsEnum,
  IsDateString,
  Length,
} from 'class-validator';
import { CallIntent } from '../entities/call.entity';

/**
 * AI gọi ngay đầu cuộc gọi, sau khi tra được nhà hàng từ hotline.
 *
 * Gọi lại với cùng call_id thì trả về bản ghi cũ chứ không tạo thêm — AI có thể thử lại
 * an toàn mà không sợ sinh hai dòng cho một cuộc gọi.
 */
export class StartCallDto {
  @ApiProperty({
    description: 'Mã cuộc gọi do nhà mạng cấp (Telnyx call_control_id hoặc callId)',
    example: 'v3:abc123def456',
    maxLength: 128,
  })
  @IsNotEmpty({ message: 'Mã cuộc gọi không được để trống' })
  @IsString({ message: 'Mã cuộc gọi phải là chuỗi' })
  @Length(1, 128, { message: 'Mã cuộc gọi phải từ 1-128 ký tự' })
  call_id: string;

  @ApiPropertyOptional({ description: 'ID nhà hàng, nếu tra được từ hotline' })
  @IsOptional()
  @IsUUID('4', { message: 'ID nhà hàng phải là UUID hợp lệ' })
  restaurant_id?: string;

  @ApiPropertyOptional({ description: 'ID chi nhánh, nếu đã khoá được ngay từ đầu' })
  @IsOptional()
  @IsUUID('4', { message: 'ID chi nhánh phải là UUID hợp lệ' })
  branch_id?: string;

  @ApiPropertyOptional({ description: 'Tên cửa hàng đọc trong lời chào', maxLength: 255 })
  @IsOptional()
  @IsString()
  @Length(0, 255)
  store_name?: string;

  @ApiPropertyOptional({ description: 'Số khách gọi đến từ đó', example: '+84912345678' })
  @IsOptional()
  @IsString()
  @Length(0, 32)
  from_number?: string;

  @ApiPropertyOptional({ description: 'Hotline khách đã bấm', example: '1900636886' })
  @IsOptional()
  @IsString()
  @Length(0, 32)
  to_number?: string;

  @ApiPropertyOptional({ description: 'Ngôn ngữ cuộc gọi', example: 'en' })
  @IsOptional()
  @IsString()
  @Length(0, 16)
  locale?: string;

  @ApiPropertyOptional({ enum: CallIntent, description: 'Ý định ban đầu, nếu khách đã bấm phím' })
  @IsOptional()
  @IsEnum(CallIntent, { message: 'Ý định không hợp lệ' })
  intent?: CallIntent;

  @ApiPropertyOptional({ description: 'Thời điểm bắt đầu (ISO 8601)' })
  @IsOptional()
  @IsDateString({}, { message: 'Thời điểm bắt đầu phải theo ISO 8601' })
  started_at?: string;
}
