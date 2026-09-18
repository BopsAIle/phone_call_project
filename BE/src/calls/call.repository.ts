import { Injectable } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository, FindManyOptions, In } from 'typeorm';
import { Call } from './entities/call.entity';
import { CallMessage } from './entities/call-message.entity';

@Injectable()
export class CallRepository {
  constructor(
    @InjectRepository(Call)
    private readonly calls: Repository<Call>,
    @InjectRepository(CallMessage)
    private readonly messages: Repository<CallMessage>,
  ) {}

  async create(data: Partial<Call>): Promise<Call> {
    return await this.calls.save(this.calls.create(data));
  }

  async findByCallId(callId: string): Promise<Call | null> {
    return await this.calls.findOne({ where: { call_id: callId } });
  }

  async findById(id: string): Promise<Call | null> {
    return await this.calls.findOne({ where: { id } });
  }

  async findAll(options?: FindManyOptions<Call>): Promise<Call[]> {
    return await this.calls.find({
      order: { started_at: 'DESC', created_at: 'DESC' },
      take: 100,
      ...options,
    });
  }

  async update(id: string, data: Partial<Call>): Promise<Call | null> {
    await this.calls.update(id, data);
    return await this.findById(id);
  }

  async findMessages(callId: string): Promise<CallMessage[]> {
    return await this.messages.find({
      where: { call_id: callId },
      order: { sequence: 'ASC' },
    });
  }

  async existingSequences(callId: string, sequences: number[]): Promise<Set<number>> {
    if (sequences.length === 0) return new Set();
    const rows = await this.messages.find({
      where: { call_id: callId, sequence: In(sequences) },
      select: { sequence: true },
    });
    return new Set(rows.map((row) => row.sequence));
  }

  async insertMessages(rows: Partial<CallMessage>[]): Promise<number> {
    if (rows.length === 0) return 0;
    // orIgnore: hai tiến trình cùng đẩy một lô thì bản thứ hai rơi im lặng thay vì 500.
    const result = await this.messages
      .createQueryBuilder()
      .insert()
      .into(CallMessage)
      .values(rows)
      .orIgnore()
      .execute();
    return result.identifiers.filter(Boolean).length;
  }

  async countMessages(callId: string): Promise<number> {
    return await this.messages.count({ where: { call_id: callId } });
  }
}
