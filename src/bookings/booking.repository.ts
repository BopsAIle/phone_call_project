import { Injectable } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository, FindOptionsWhere, FindManyOptions, Between } from 'typeorm';
import { Booking, BookingStatus, BookingSource } from './entities/booking.entity';

@Injectable()
export class BookingRepository {
  constructor(
    @InjectRepository(Booking)
    private readonly repository: Repository<Booking>,
  ) {}

  async create(data: Partial<Booking>): Promise<Booking> {
    const entity = this.repository.create(data);
    return await this.repository.save(entity);
  }

  async findAll(options?: FindManyOptions<Booking>): Promise<Booking[]> {
    return await this.repository.find({
      relations: { restaurant: true, branch: true },
      order: { created_at: 'DESC' },
      ...options,
    });
  }

  async findById(id: string): Promise<Booking | null> {
    return await this.repository.findOne({ 
      where: { id },
      relations: { restaurant: true, branch: true },
    });
  }

  async findByRestaurantId(restaurantId: string): Promise<Booking[]> {
    return await this.repository.find({
      where: { restaurant_id: restaurantId },
      relations: { restaurant: true, branch: true },
      order: { booking_date: 'DESC', booking_time: 'DESC' },
    });
  }

  async findByBranchId(branchId: string): Promise<Booking[]> {
    return await this.repository.find({
      where: { branch_id: branchId },
      relations: { restaurant: true, branch: true },
      order: { booking_date: 'DESC', booking_time: 'DESC' },
    });
  }

  async findByStatus(status: BookingStatus): Promise<Booking[]> {
    return await this.repository.find({
      where: { status },
      relations: { restaurant: true, branch: true },
      order: { booking_date: 'DESC', booking_time: 'DESC' },
    });
  }

  async findBySource(source: BookingSource): Promise<Booking[]> {
    return await this.repository.find({
      where: { source },
      relations: { restaurant: true, branch: true },
      order: { created_at: 'DESC' },
    });
  }

  async findByCustomerPhone(phoneNumber: string): Promise<Booking[]> {
    return await this.repository.find({
      where: { phone_number: phoneNumber },
      relations: { restaurant: true, branch: true },
      order: { created_at: 'DESC' },
    });
  }

  async findByDateRange(startDate: Date, endDate: Date): Promise<Booking[]> {
    return await this.repository.find({
      where: { 
        booking_date: Between(startDate, endDate) 
      },
      relations: { restaurant: true, branch: true },
      order: { booking_date: 'ASC', booking_time: 'ASC' },
    });
  }

  async findByBranchAndDate(branchId: string, date: Date): Promise<Booking[]> {
    return await this.repository.find({
      where: { 
        branch_id: branchId,
        booking_date: date,
      },
      relations: { restaurant: true, branch: true },
      order: { booking_time: 'ASC' },
    });
  }

  async update(id: string, data: Partial<Booking>): Promise<Booking> {
    await this.repository.update(id, data);
    const updated = await this.findById(id);
    if (!updated) {
      throw new Error(`Không thể cập nhật đặt bàn với ID ${id}`);
    }
    return updated;
  }

  async delete(id: string): Promise<void> {
    await this.repository.delete(id);
  }

  async count(where?: FindOptionsWhere<Booking>): Promise<number> {
    return await this.repository.count({ where });
  }

  async exists(where: FindOptionsWhere<Booking>): Promise<boolean> {
    const count = await this.repository.count({ where });
    return count > 0;
  }

  async countByRestaurant(restaurantId: string): Promise<number> {
    return await this.repository.count({ where: { restaurant_id: restaurantId } });
  }

  async countByBranch(branchId: string): Promise<number> {
    return await this.repository.count({ where: { branch_id: branchId } });
  }

  async countByStatus(status: BookingStatus): Promise<number> {
    return await this.repository.count({ where: { status } });
  }
}