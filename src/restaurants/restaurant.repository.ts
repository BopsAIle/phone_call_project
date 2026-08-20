import { Injectable } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository, FindOptionsWhere, FindManyOptions } from 'typeorm';
import { Restaurant, RestaurantStatus } from './entities/restaurant.entity';

@Injectable()
export class RestaurantRepository {
  constructor(
    @InjectRepository(Restaurant)
    private readonly repository: Repository<Restaurant>,
  ) {}

  async create(data: Partial<Restaurant>): Promise<Restaurant> {
    const entity = this.repository.create(data);
    return await this.repository.save(entity);
  }

  async findAll(options?: FindManyOptions<Restaurant>): Promise<Restaurant[]> {
    return await this.repository.find({
      order: { created_at: 'DESC' },
      ...options,
    });
  }

  async findById(id: string): Promise<Restaurant | null> {
    return await this.repository.findOne({ where: { id } });
  }

  async findByName(name: string): Promise<Restaurant | null> {
    return await this.repository.findOne({ where: { name } });
  }

  async findByStatus(status: RestaurantStatus): Promise<Restaurant[]> {
    return await this.repository.find({
      where: { status },
      order: { created_at: 'DESC' },
    });
  }

  async update(id: string, data: Partial<Restaurant>): Promise<Restaurant> {
    await this.repository.update(id, data);
    const updated = await this.findById(id);
    if (!updated) {
      throw new Error(`Không thể cập nhật nhà hàng với ID ${id}`);
    }
    return updated;
  }

  async delete(id: string): Promise<void> {
    await this.repository.delete(id);
  }

  async count(where?: FindOptionsWhere<Restaurant>): Promise<number> {
    return await this.repository.count({ where });
  }

  async exists(where: FindOptionsWhere<Restaurant>): Promise<boolean> {
    const count = await this.repository.count({ where });
    return count > 0;
  }

  async findByPhone(phone: string): Promise<Restaurant | null> {
    return await this.repository.findOne({
      where: { phone },
      relations: { branches: true },
    });
  }
}