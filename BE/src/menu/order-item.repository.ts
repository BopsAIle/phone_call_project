import { Injectable } from '@nestjs/common';
import { DataSource, Repository } from 'typeorm';
import { OrderItem } from './entities/order-item.entity';

@Injectable()
export class OrderItemRepository {
  private readonly repository: Repository<OrderItem>;

  constructor(private readonly dataSource: DataSource) {
    this.repository = this.dataSource.getRepository(OrderItem);
  }

  async create(data: Partial<OrderItem>): Promise<OrderItem> {
    return await this.repository.save(data);
  }

  async createMultiple(data: Partial<OrderItem>[]): Promise<OrderItem[]> {
    return await this.repository.save(data);
  }

  async findByBookingId(bookingId: string): Promise<OrderItem[]> {
    return await this.repository.find({
      where: { booking_id: bookingId },
      relations: { menu_item: true },
    });
  }

  async findById(id: string): Promise<OrderItem | null> {
    return await this.repository.findOne({
      where: { id },
      relations: { menu_item: true },
    });
  }

  async delete(id: string): Promise<void> {
    await this.repository.delete(id);
  }

  async deleteByBookingId(bookingId: string): Promise<void> {
    await this.repository.delete({ booking_id: bookingId });
  }
}
