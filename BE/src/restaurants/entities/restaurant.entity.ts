import {
  Entity,
  PrimaryGeneratedColumn,
  Column,
  CreateDateColumn,
  UpdateDateColumn,
  OneToMany,
} from 'typeorm';

export enum RestaurantStatus {
  ACTIVE = 'active',
  INACTIVE = 'inactive',
}

@Entity('restaurants')
export class Restaurant {
  @PrimaryGeneratedColumn('uuid')
  id: string;

  @Column({ type: 'varchar', length: 255, nullable: false })
  name: string;

  @Column({ type: 'varchar', length: 20, nullable: true })
  phone: string;

  @Column({
    type: 'enum',
    enum: RestaurantStatus,
    default: RestaurantStatus.ACTIVE,
  })
  status: RestaurantStatus;

  @CreateDateColumn({ type: 'timestamp' })
  created_at: Date;

  @UpdateDateColumn({ type: 'timestamp' })
  updated_at: Date;

  // Relations
  @OneToMany(() => Branch, (branch) => branch.restaurant)
  branches: Branch[];
}

// Import Branch ở đây để tránh circular dependency
import { Branch } from '../../branches/entities/branch.entity';