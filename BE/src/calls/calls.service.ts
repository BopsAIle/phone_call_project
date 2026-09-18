import { Injectable, Logger, NotFoundException } from '@nestjs/common';
import { CallRepository } from './call.repository';
import { Call, CallIntent, CallStatus } from './entities/call.entity';
import { CallMessage } from './entities/call-message.entity';
import { StartCallDto } from './dto/start-call.dto';
import { AppendCallMessagesDto, CallMessageDto } from './dto/append-messages.dto';
import { EndCallDto } from './dto/end-call.dto';

@Injectable()
export class CallsService {
  private readonly logger = new Logger(CallsService.name);

  constructor(private readonly repository: CallRepository) {}

  /**
   * Tạo bản ghi cuộc gọi, hoặc trả về bản ghi cũ nếu call_id đã có.
   *
   * Idempotent theo call_id: AI thử lại khi mạng chập chờn mà không sinh bản ghi trùng.
   */
  async start(dto: StartCallDto): Promise<Call> {
    const existing = await this.repository.findByCallId(dto.call_id);
    if (existing) {
      this.logger.log(`Cuộc gọi ${dto.call_id} đã tồn tại, trả về bản ghi cũ`);
      return existing;
    }
    return await this.repository.create({
      call_id: dto.call_id,
      restaurant_id: dto.restaurant_id ?? null,
      branch_id: dto.branch_id ?? null,
      store_name: dto.store_name ?? null,
      from_number: dto.from_number ?? null,
      to_number: dto.to_number ?? null,
      locale: dto.locale ?? null,
      intent: dto.intent ?? CallIntent.UNKNOWN,
      status: CallStatus.IN_PROGRESS,
      started_at: dto.started_at ? new Date(dto.started_at) : new Date(),
    });
  }

  async appendMessages(id: string, dto: AppendCallMessagesDto): Promise<{ added: number; total: number }> {
    const call = await this.requireCall(id);
    const added = await this.insert(call.id, dto.messages);
    return { added, total: await this.repository.countMessages(call.id) };
  }

  async end(id: string, dto: EndCallDto): Promise<Call> {
    const call = await this.requireCall(id);
    if (dto.messages?.length) {
      await this.insert(call.id, dto.messages);
    }
    const endedAt = dto.ended_at ? new Date(dto.ended_at) : new Date();
    const duration =
      dto.duration_seconds ??
      (call.started_at
        ? Math.max(0, Math.round((endedAt.getTime() - call.started_at.getTime()) / 1000))
        : null);
    const updated = await this.repository.update(call.id, {
      status: dto.status ?? CallStatus.COMPLETED,
      ...(dto.intent ? { intent: dto.intent } : {}),
      ...(dto.branch_id ? { branch_id: dto.branch_id } : {}),
      ...(dto.booking_id ? { booking_id: dto.booking_id } : {}),
      ...(dto.order_id ? { order_id: dto.order_id } : {}),
      ended_at: endedAt,
      duration_seconds: duration,
      end_reason: dto.end_reason ?? null,
    });
    return updated ?? call;
  }

  async findAll(filters: { restaurant_id?: string; branch_id?: string; status?: CallStatus }): Promise<Call[]> {
    const where: Record<string, unknown> = {};
    if (filters.restaurant_id) where.restaurant_id = filters.restaurant_id;
    if (filters.branch_id) where.branch_id = filters.branch_id;
    if (filters.status) where.status = filters.status;
    return await this.repository.findAll(
      Object.keys(where).length ? { where } : undefined,
    );
  }

  /** Cuộc gọi kèm toàn bộ transcript — cái để đối chiếu khi khách khiếu nại đơn. */
  async findOneWithTranscript(id: string): Promise<Call & { messages: CallMessage[] }> {
    const call = await this.requireCall(id);
    const messages = await this.repository.findMessages(call.id);
    return { ...call, messages };
  }

  async findByCallId(callId: string): Promise<Call> {
    const call = await this.repository.findByCallId(callId);
    if (!call) {
      throw new NotFoundException(`Không tìm thấy cuộc gọi với mã ${callId}`);
    }
    return call;
  }

  private async insert(callId: string, messages: CallMessageDto[]): Promise<number> {
    // Bỏ trước những sequence đã có, để lô gửi lại không nở ra lỗi khoá trùng.
    const already = await this.repository.existingSequences(
      callId,
      messages.map((m) => m.sequence),
    );
    const rows = messages
      .filter((m) => !already.has(m.sequence))
      .map((m) => ({
        call_id: callId,
        sequence: m.sequence,
        role: m.role,
        content: m.content,
        tool_name: m.tool_name ?? null,
        spoken_at: m.spoken_at ? new Date(m.spoken_at) : null,
      }));
    return await this.repository.insertMessages(rows);
  }

  private async requireCall(id: string): Promise<Call> {
    const call = await this.repository.findById(id);
    if (!call) {
      throw new NotFoundException(`Không tìm thấy cuộc gọi ${id}`);
    }
    return call;
  }
}
