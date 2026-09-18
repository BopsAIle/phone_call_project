import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { Type } from 'class-transformer';
import {
  ArrayMaxSize,
  ArrayNotEmpty,
  IsArray,
  IsDateString,
  IsEnum,
  IsInt,
  IsNotEmpty,
  IsOptional,
  IsString,
  Length,
  Min,
  ValidateNested,
} from 'class-validator';
import { CallMessageRole } from '../entities/call-message.entity';

export class CallMessageDto {
  @ApiProperty({ description: 'Thứ tự trong cuộc gọi, bắt đầu từ 0', example: 0 })
  @IsInt({ message: 'Thứ tự phải là số nguyên' })
  @Min(0, { message: 'Thứ tự không được âm' })
  sequence: number;

  @ApiProperty({ enum: CallMessageRole, description: 'Ai nói câu này' })
  @IsEnum(CallMessageRole, { message: 'Vai không hợp lệ' })
  role: CallMessageRole;

  @ApiProperty({ description: 'Nội dung câu nói, hoặc JSON kết quả tool' })
  @IsNotEmpty({ message: 'Nội dung không được để trống' })
  @IsString({ message: 'Nội dung phải là chuỗi' })
  content: string;

  @ApiPropertyOptional({ description: 'Tên công cụ, chỉ khi role = tool' })
  @IsOptional()
  @IsString()
  @Length(0, 100)
  tool_name?: string;

  @ApiPropertyOptional({ description: 'Thời điểm câu này xảy ra (ISO 8601)' })
  @IsOptional()
  @IsDateString({}, { message: 'Thời điểm phải theo ISO 8601' })
  spoken_at?: string;
}

/**
 * AI đẩy transcript theo lô trong lúc cuộc gọi đang diễn ra, để một cuộc gọi bị rớt
 * giữa chừng vẫn còn lại phần đã nói.
 *
 * Gửi lại một lô đã gửi là an toàn: (call_id, sequence) là khoá duy nhất, trùng thì bỏ qua.
 */
export class AppendCallMessagesDto {
  @ApiProperty({ type: [CallMessageDto], description: 'Các lượt nói, tối đa 200 mỗi lô' })
  @IsArray()
  @ArrayNotEmpty({ message: 'Lô tin nhắn không được rỗng' })
  @ArrayMaxSize(200, { message: 'Mỗi lô tối đa 200 tin nhắn' })
  @ValidateNested({ each: true })
  @Type(() => CallMessageDto)
  messages: CallMessageDto[];
}
