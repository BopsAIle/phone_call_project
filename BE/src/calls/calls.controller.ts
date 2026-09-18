import { Body, Controller, Get, Param, ParseUUIDPipe, Post, Query } from '@nestjs/common';
import {
  ApiBody,
  ApiOperation,
  ApiParam,
  ApiQuery,
  ApiResponse,
  ApiTags,
} from '@nestjs/swagger';
import { CallsService } from './calls.service';
import { StartCallDto } from './dto/start-call.dto';
import { AppendCallMessagesDto } from './dto/append-messages.dto';
import { EndCallDto } from './dto/end-call.dto';
import { Call, CallStatus } from './entities/call.entity';

@ApiTags('Calls')
@Controller('calls')
export class CallsController {
  constructor(private readonly callsService: CallsService) {}

  @Post('ai/start')
  @ApiOperation({
    summary: 'Mở bản ghi cuộc gọi từ AI voice',
    description:
      'Gọi ngay đầu cuộc gọi. Idempotent theo call_id — gọi lại trả về bản ghi cũ, không tạo trùng.',
  })
  @ApiBody({ type: StartCallDto })
  @ApiResponse({ status: 201, description: 'Đã mở bản ghi cuộc gọi', type: Call })
  async start(@Body() dto: StartCallDto): Promise<Call> {
    return await this.callsService.start(dto);
  }

  @Post('ai/:id/messages')
  @ApiOperation({
    summary: 'Đẩy một lô transcript',
    description:
      'Gọi định kỳ trong lúc cuộc gọi đang chạy, để cuộc gọi rớt giữa chừng vẫn còn phần đã nói. ' +
      'Gửi lại một lô đã gửi là an toàn: (call_id, sequence) là khoá duy nhất.',
  })
  @ApiParam({ name: 'id', description: 'ID bản ghi cuộc gọi (trả về từ /calls/ai/start)' })
  @ApiBody({ type: AppendCallMessagesDto })
  @ApiResponse({ status: 201, description: 'Đã ghi transcript' })
  @ApiResponse({ status: 404, description: 'Không tìm thấy cuộc gọi' })
  async appendMessages(
    @Param('id', new ParseUUIDPipe({ version: '4' })) id: string,
    @Body() dto: AppendCallMessagesDto,
  ): Promise<{ added: number; total: number }> {
    return await this.callsService.appendMessages(id, dto);
  }

  @Post('ai/:id/end')
  @ApiOperation({
    summary: 'Chốt cuộc gọi',
    description: 'Ghi thời điểm kết thúc, thời lượng, trạng thái, và lô transcript còn lại.',
  })
  @ApiParam({ name: 'id', description: 'ID bản ghi cuộc gọi' })
  @ApiBody({ type: EndCallDto })
  @ApiResponse({ status: 201, description: 'Đã chốt cuộc gọi', type: Call })
  @ApiResponse({ status: 404, description: 'Không tìm thấy cuộc gọi' })
  async end(
    @Param('id', new ParseUUIDPipe({ version: '4' })) id: string,
    @Body() dto: EndCallDto,
  ): Promise<Call> {
    return await this.callsService.end(id, dto);
  }

  @Get()
  @ApiOperation({ summary: 'Danh sách cuộc gọi gần đây' })
  @ApiQuery({ name: 'restaurant_id', required: false })
  @ApiQuery({ name: 'branch_id', required: false })
  @ApiQuery({ name: 'status', required: false, enum: CallStatus })
  @ApiResponse({ status: 200, description: 'Danh sách cuộc gọi', type: [Call] })
  async findAll(
    @Query('restaurant_id') restaurantId?: string,
    @Query('branch_id') branchId?: string,
    @Query('status') status?: CallStatus,
  ): Promise<Call[]> {
    return await this.callsService.findAll({
      restaurant_id: restaurantId,
      branch_id: branchId,
      status,
    });
  }

  @Get('by-call-id/:callId')
  @ApiOperation({ summary: 'Tra cuộc gọi theo mã của nhà mạng' })
  @ApiParam({ name: 'callId', description: 'Mã cuộc gọi do nhà mạng cấp' })
  @ApiResponse({ status: 404, description: 'Không tìm thấy cuộc gọi' })
  async findByCallId(@Param('callId') callId: string): Promise<Call> {
    return await this.callsService.findByCallId(callId);
  }

  @Get(':id')
  @ApiOperation({
    summary: 'Chi tiết cuộc gọi kèm transcript',
    description: 'Đây là thứ để đối chiếu khi khách khiếu nại đơn.',
  })
  @ApiParam({ name: 'id', description: 'ID bản ghi cuộc gọi' })
  @ApiResponse({ status: 404, description: 'Không tìm thấy cuộc gọi' })
  async findOne(@Param('id', new ParseUUIDPipe({ version: '4' })) id: string) {
    return await this.callsService.findOneWithTranscript(id);
  }
}
