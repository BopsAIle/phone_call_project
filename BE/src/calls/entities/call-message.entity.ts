import {
  Entity,
  PrimaryGeneratedColumn,
  Column,
  CreateDateColumn,
  ManyToOne,
  JoinColumn,
  Index,
} from 'typeorm';
import { Call } from './call.entity';

export enum CallMessageRole {
  /** Câu người gọi nói (bản STT nghe được). */
  USER = 'user',
  /** Câu AI thật sự phát ra loa — không phải câu model định nói rồi bị ngắt. */
  ASSISTANT = 'assistant',
  /** Một lần gọi công cụ và kết quả, giữ lại để truy vết khi có khiếu nại. */
  TOOL = 'tool',
}

@Entity('call_messages')
@Index(['call_id', 'sequence'], { unique: true })
export class CallMessage {
  @PrimaryGeneratedColumn('uuid')
  id: string;

  @Column({ type: 'uuid' })
  call_id: string;

  /** Thứ tự trong cuộc gọi, bắt đầu từ 0. Dùng để chống ghi trùng khi AI gửi lại lô. */
  @Column({ type: 'int' })
  sequence: number;

  @Column({ type: 'enum', enum: CallMessageRole })
  role: CallMessageRole;

  @Column({ type: 'text' })
  content: string;

  /** Chỉ có giá trị khi role = tool. */
  @Column({ type: 'varchar', length: 100, nullable: true })
  tool_name: string | null;

  /** Thời điểm câu này xảy ra trong cuộc gọi, do AI gửi lên. */
  @Column({ type: 'timestamp', nullable: true })
  spoken_at: Date | null;

  @CreateDateColumn({ type: 'timestamp' })
  created_at: Date;

  @ManyToOne(() => Call, (call) => call.messages, { onDelete: 'CASCADE' })
  @JoinColumn({ name: 'call_id' })
  call: Call;
}
