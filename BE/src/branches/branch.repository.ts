import { Injectable } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository, FindOptionsWhere, FindManyOptions } from 'typeorm';
import { Branch, BranchStatus } from './entities/branch.entity';

@Injectable()
export class BranchRepository {
  constructor(
    @InjectRepository(Branch)
    private readonly repository: Repository<Branch>,
  ) {}

  async create(data: Partial<Branch>): Promise<Branch> {
    const entity = this.repository.create(data);
    return await this.repository.save(entity);
  }

  async findAll(options?: FindManyOptions<Branch>): Promise<Branch[]> {
    return await this.repository.find({
      relations: { restaurant: true },
      order: { created_at: 'DESC' },
      ...options,
    });
  }

  async findById(id: string): Promise<Branch | null> {
    return await this.repository.findOne({ 
      where: { id },
      relations: { restaurant: true },
    });
  }

  async findByRestaurantId(restaurantId: string): Promise<Branch[]> {
    return await this.repository.find({
      where: { restaurant_id: restaurantId },
      relations: { restaurant: true },
      order: { created_at: 'DESC' },
    });
  }

  async findByName(name: string): Promise<Branch | null> {
    return await this.repository.findOne({ 
      where: { name },
      relations: { restaurant: true },
    });
  }

  async findByStatus(status: BranchStatus): Promise<Branch[]> {
    return await this.repository.find({
      where: { status },
      relations: { restaurant: true },
      order: { created_at: 'DESC' },
    });
  }

  async update(id: string, data: Partial<Branch>): Promise<Branch> {
    await this.repository.update(id, data);
    const updated = await this.findById(id);
    if (!updated) {
      throw new Error(`Không thể cập nhật chi nhánh với ID ${id}`);
    }
    return updated;
  }

  async delete(id: string): Promise<void> {
    await this.repository.delete(id);
  }

  async count(where?: FindOptionsWhere<Branch>): Promise<number> {
    return await this.repository.count({ where });
  }

  async exists(where: FindOptionsWhere<Branch>): Promise<boolean> {
    const count = await this.repository.count({ where });
    return count > 0;
  }

  async countByRestaurant(restaurantId: string): Promise<number> {
    return await this.repository.count({ where: { restaurant_id: restaurantId } });
  }

  async findByPhone(phone: string): Promise<Branch | null> {
    return await this.repository.findOne({
      where: { phone },
      relations: { restaurant: true },
    });
  }
}