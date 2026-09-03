import { Injectable } from '@nestjs/common';
import { DataSource, Repository, In } from 'typeorm';
import { MenuItem } from './entities/menu-item.entity';

@Injectable()
export class MenuRepository {
  private readonly repository: Repository<MenuItem>;

  constructor(private readonly dataSource: DataSource) {
    this.repository = this.dataSource.getRepository(MenuItem);
  }

  async create(data: Partial<MenuItem>): Promise<MenuItem> {
    return await this.repository.save(data);
  }

  async findAll(options?): Promise<MenuItem[]> {
    return await this.repository.find(options);
  }

  async findByBranchId(branchId: string): Promise<MenuItem[]> {
    return await this.repository.find({
      where: { branch_id: branchId },
    });
  }

  async findById(id: string): Promise<MenuItem | null> {
    return await this.repository.findOne({
      where: { id },
    });
  }

  async findByIds(ids: string[]): Promise<MenuItem[]> {
    return await this.repository.find({
      where: { id: In(ids) },
    });
  }

  async findByBranchAndIds(branchId: string, ids: string[]): Promise<MenuItem[]> {
    return await this.repository.find({
      where: { 
        branch_id: branchId,
        id: In(ids),
      },
    });
  }

  async update(id: string, data: Partial<MenuItem>): Promise<MenuItem | null> {
    await this.repository.update(id, data);
    return await this.findById(id);
  }

  async delete(id: string): Promise<void> {
    await this.repository.delete(id);
  }

  async count(): Promise<number> {
    return await this.repository.count();
  }
}
