import { Injectable, NotFoundException, ConflictException } from '@nestjs/common';
import { Branch } from './entities/branch.entity';
import { CreateBranchDto } from './dto/create-branch.dto';
import { UpdateBranchDto } from './dto/update-branch.dto';
import { BranchRepository } from './branch.repository';
import { RestaurantsService } from '../restaurants/restaurants.service';

@Injectable()
export class BranchesService {
  constructor(
    private readonly branchRepository: BranchRepository,
    private readonly restaurantsService: RestaurantsService,
  ) {}

  async create(createBranchDto: CreateBranchDto): Promise<Branch> {
    // Business logic: Check if restaurant exists
    await this.restaurantsService.findOne(createBranchDto.restaurant_id);

    // Business logic: Check if branch name exists
    const existingBranch = await this.branchRepository.findByName(createBranchDto.name);
    if (existingBranch) {
      throw new ConflictException(`Chi nhánh với tên "${createBranchDto.name}" đã tồn tại`);
    }

    return await this.branchRepository.create(createBranchDto);
  }

  async findAll(): Promise<Branch[]> {
    return await this.branchRepository.findAll();
  }

  async findOne(id: string): Promise<Branch> {
    const branch = await this.branchRepository.findById(id);

    if (!branch) {
      throw new NotFoundException(`Không tìm thấy chi nhánh với ID ${id}`);
    }

    return branch;
  }

  async findByRestaurant(restaurantId: string): Promise<Branch[]> {
    // Check if restaurant exists
    await this.restaurantsService.findOne(restaurantId);
    
    return await this.branchRepository.findByRestaurantId(restaurantId);
  }

  async update(id: string, updateBranchDto: UpdateBranchDto): Promise<Branch> {
    const branch = await this.findOne(id);
    
    // Business logic: Check name conflict if updating name
    if (updateBranchDto.name && updateBranchDto.name !== branch.name) {
      const existingBranch = await this.branchRepository.findByName(updateBranchDto.name);
      if (existingBranch) {
        throw new ConflictException(`Chi nhánh với tên "${updateBranchDto.name}" đã tồn tại`);
      }
    }
    
    return await this.branchRepository.update(id, updateBranchDto);
  }

  async remove(id: string): Promise<void> {
    await this.findOne(id); // Check if exists
    await this.branchRepository.delete(id);
  }

  async findByStatus(status: string): Promise<Branch[]> {
    return await this.branchRepository.findByStatus(status as any);
  }

  async getRestaurantBranchCount(restaurantId: string): Promise<number> {
    return await this.branchRepository.countByRestaurant(restaurantId);
  }

  async findByPhone(phone: string): Promise<Branch | null> {
    return await this.branchRepository.findByPhone(phone);
  }
}