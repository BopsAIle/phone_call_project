import { Entity, PrimaryGeneratedColumn, Column, CreateDateColumn, UpdateDateColumn, ManyToOne, JoinColumn } from 'typeorm';
import { Restaurant } from '../../restaurants/entities/restaurant.entity';
import { Branch } from '../../branches/entities/branch.entity';

export enum BookingSource {
  WEBSITE = 'website',
  PHONE_AI = 'phone_ai',
  PHONE_HUMAN = 'phone_human',
  WALK_IN = 'walk_in',
  APP = 'app',
  SOCIAL_MEDIA = 'social_media',
  THIRD_PARTY = 'third_party',
}

export enum BookingStatus {
  PENDING = 'pending',
  CONFIRMED = 'confirmed',
  CANCELLED = 'cancelled',
  COMPLETED = 'completed',
  NO_SHOW = 'no_show',
}

export enum ShipperStatus {
  PENDING = 'pending',
  ASSIGNED = 'assigned',
  PICKED_UP = 'picked_up',
  ON_THE_WAY = 'on_the_way',
  DELIVERED = 'delivered',
  CANCELLED = 'cancelled',
}

export enum BookingType {
  DINE_IN = 'dine_in',
  TAKEOUT = 'takeout',
  DELIVERY = 'delivery',
}

@Entity('bookings')
export class Booking {
  @PrimaryGeneratedColumn('uuid')
  id: string;

  @Column({ type: 'uuid' })
  restaurant_id: string;

  @Column({ type: 'uuid' })
  branch_id: string;

  @Column({ type: 'varchar', length: 255, nullable: false })
  customer_name: string;

  @Column({ type: 'varchar', length: 20, nullable: false })
  phone_number: string;

  @Column({ type: 'int', nullable: true })
  party_size: number;

  @Column({ type: 'date', nullable: false })
  booking_date: Date;

  @Column({ type: 'time', nullable: false })
  booking_time: string;

  @Column({ type: 'enum', enum: BookingType, default: BookingType.DINE_IN })
  booking_type: BookingType;

  @Column({ type: 'decimal', precision: 10, scale: 2, nullable: true })
  total_price: number;

  @Column({ type: 'text', nullable: true })
  note: string;

  @Column({ type: 'enum', enum: BookingSource, default: BookingSource.PHONE_AI })
  source: BookingSource;

  @Column({ type: 'enum', enum: BookingStatus, default: BookingStatus.PENDING })
  status: BookingStatus;

  @Column({ type: 'varchar', length: 500, nullable: true })
  delivery_address: string;

  @Column({ type: 'varchar', length: 20, nullable: true })
  delivery_phone: string;

  @Column({ type: 'decimal', precision: 10, scale: 2, nullable: true })
  delivery_fee: number;

  @Column({ type: 'varchar', length: 5, nullable: true })
  estimated_delivery_time: string; // HH:MM format

  @Column({ type: 'varchar', length: 5, nullable: true })
  actual_delivery_time: string; // HH:MM format

  @Column({
    type: 'enum',
    enum: ShipperStatus,
    nullable: true,
    default: null,
  })
  shipper_status: ShipperStatus;

  @CreateDateColumn({ type: 'timestamp' })
  created_at: Date;

  @UpdateDateColumn({ type: 'timestamp' })
  updated_at: Date;

  @ManyToOne(() => Restaurant, { onDelete: 'CASCADE' })
  @JoinColumn({ name: 'restaurant_id' })
  restaurant: Restaurant;

  @ManyToOne(() => Branch, { onDelete: 'CASCADE' })
  @JoinColumn({ name: 'branch_id' })
  branch: Branch;
}
