import {
  Entity,
  PrimaryGeneratedColumn,
  Column,
  CreateDateColumn,
  UpdateDateColumn,
  Index,
  OneToMany,
} from 'typeorm';
import { CallMessage } from './call-message.entity';

export enum CallStatus {
  IN_PROGRESS = 'in_progress',
  COMPLETED = 'completed',
  FAILED = 'failed',
}

export enum CallIntent {
  UNKNOWN = 'unknown',
  BOOKING = 'booking',
  PICKUP = 'pickup',
  DELIVERY = 'delivery',
}

/**
 * Một cuộc gọi vào tổng đài AI.
 *
 * restaurant_id / branch_id cố ý để là cột uuid thường, KHÔNG phải quan hệ khoá ngoại:
 * cuộc gọi vào số lạ thì không có nhà hàng nào, và xoá một chi nhánh cũng không được
 * phép xoá mất bằng chứng cuộc gọi đã diễn ra.
 */
@Entity('calls')
export class Call {
  @PrimaryGeneratedColumn('uuid')
  id: string;

  /** Mã cuộc gọi do nhà mạng cấp. Dùng làm khoá chống trùng khi AI gọi lại. */
  @Index({ unique: true })
  @Column({ type: 'varchar', length: 128 })
  call_id: string;

  @Column({ type: 'uuid', nullable: true })
  restaurant_id: string | null;

  @Column({ type: 'uuid', nullable: true })
  branch_id: string | null;

  @Column({ type: 'varchar', length: 255, nullable: true })
  store_name: string | null;

  /** Số khách gọi đến từ đó. */
  @Column({ type: 'varchar', length: 32, nullable: true })
  from_number: string | null;

  /** Hotline của nhà hàng mà khách bấm. */
  @Column({ type: 'varchar', length: 32, nullable: true })
  to_number: string | null;

  @Column({ type: 'varchar', length: 16, nullable: true })
  locale: string | null;

  @Column({ type: 'enum', enum: CallStatus, default: CallStatus.IN_PROGRESS })
  status: CallStatus;

  @Column({ type: 'enum', enum: CallIntent, default: CallIntent.UNKNOWN })
  intent: CallIntent;

  /** Đơn đặt bàn / đặt món do cuộc gọi này tạo ra, nếu có. */
  @Column({ type: 'uuid', nullable: true })
  booking_id: string | null;

  @Column({ type: 'uuid', nullable: true })
  order_id: string | null;

  @Column({ type: 'timestamp', nullable: true })
  started_at: Date | null;

  @Column({ type: 'timestamp', nullable: true })
  ended_at: Date | null;

  @Column({ type: 'int', nullable: true })
  duration_seconds: number | null;

  /** Lý do kết thúc bất thường; rỗng khi cuộc gọi kết thúc bình thường. */
  @Column({ type: 'varchar', length: 255, nullable: true })
  end_reason: string | null;

  @CreateDateColumn({ type: 'timestamp' })
  created_at: Date;

  @UpdateDateColumn({ type: 'timestamp' })
  updated_at: Date;

  @OneToMany(() => CallMessage, (message) => message.call)
  messages: CallMessage[];
}
