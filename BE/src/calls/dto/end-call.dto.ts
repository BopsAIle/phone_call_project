import { ApiPropertyOptional } from '@nestjs/swagger';
import { Type } from 'class-transformer';
import {
  ArrayMaxSize,
  IsArray,
  IsDateString,
  IsEnum,
  IsInt,
  IsOptional,
  IsString,
  IsUUID,
  Length,
  Min,
  ValidateNested,
} from 'class-validator';
import { CallIntent, CallStatus } from '../entities/call.entity';
import { CallMessageDto } from './append-messages.dto';

/**
 * AI gọi khi cúp máy: chốt thời lượng, trạng thái, và đẩy nốt lô transcript còn lại.
 * Gộp hai việc vào một request để một cuộc gọi kết thúc chỉ tốn một lần đi mạng.
 */
export class EndCallDto {
  @ApiPropertyOptional({ enum: CallStatus })
  @IsOptional()
  @IsEnum(CallStatus, { message: 'Trạng thái không hợp lệ' })
  status?: CallStatus;

  @ApiPropertyOptional({ enum: CallIntent })
  @IsOptional()
  @IsEnum(CallIntent, { message: 'Ý định không hợp lệ' })
  intent?: CallIntent;

  @ApiPropertyOptional({ description: 'Chi nhánh cuối cùng đã khoá' })
  @IsOptional()
  @IsUUID('4', { message: 'ID chi nhánh phải là UUID hợp lệ' })
  branch_id?: string;

  @ApiPropertyOptional({ description: 'Đơn đặt bàn cuộc gọi này tạo ra' })
  @IsOptional()
  @IsUUID('4', { message: 'ID đặt bàn phải là UUID hợp lệ' })
  booking_id?: string;

  @ApiPropertyOptional({ description: 'Đơn đặt món cuộc gọi này tạo ra' })
  @IsOptional()
  @IsUUID('4', { message: 'ID đơn hàng phải là UUID hợp lệ' })
  order_id?: string;

  @ApiPropertyOptional({ description: 'Thời điểm kết thúc (ISO 8601)' })
  @IsOptional()
  @IsDateString({}, { message: 'Thời điểm kết thúc phải theo ISO 8601' })
  ended_at?: string;

  @ApiPropertyOptional({ description: 'Thời lượng tính bằng giây' })
  @IsOptional()
  @IsInt({ message: 'Thời lượng phải là số nguyên' })
  @Min(0, { message: 'Thời lượng không được âm' })
  duration_seconds?: number;

  @ApiPropertyOptional({ description: 'Lý do kết thúc bất thường' })
  @IsOptional()
  @IsString()
  @Length(0, 255)
  end_reason?: string;

  @ApiPropertyOptional({ type: [CallMessageDto], description: 'Lô transcript còn lại' })
  @IsOptional()
  @IsArray()
  @ArrayMaxSize(200, { message: 'Mỗi lô tối đa 200 tin nhắn' })
  @ValidateNested({ each: true })
  @Type(() => CallMessageDto)
  messages?: CallMessageDto[];
}
