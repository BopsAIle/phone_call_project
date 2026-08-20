import { Injectable, NotFoundException, ConflictException } from '@nestjs/common';
import { Restaurant } from './entities/restaurant.entity';
import { CreateRestaurantDto } from './dto/create-restaurant.dto';
import { UpdateRestaurantDto } from './dto/update-restaurant.dto';
import { RestaurantRepository } from './restaurant.repository';

@Injectable()
export class RestaurantsService {
  constructor(
    private readonly restaurantRepository: RestaurantRepository,
  ) {}

  async create(createRestaurantDto: CreateRestaurantDto): Promise<Restaurant> {
    // Business logic: Check if restaurant name exists
    const existingRestaurant = await this.restaurantRepository.findByName(createRestaurantDto.name);
    if (existingRestaurant) {
      throw new ConflictException(`Nhà hàng với tên "${createRestaurantDto.name}" đã tồn tại`);
    }

    return await this.restaurantRepository.create(createRestaurantDto);
  }

  async findAll(): Promise<Restaurant[]> {
    return await this.restaurantRepository.findAll();
  }

  async findOne(id: string): Promise<Restaurant> {
    const restaurant = await this.restaurantRepository.findById(id);

    if (!restaurant) {
      throw new NotFoundException(`Không tìm thấy nhà hàng với ID ${id}`);
    }

    return restaurant;
  }

  async update(id: string, updateRestaurantDto: UpdateRestaurantDto): Promise<Restaurant> {
    const restaurant = await this.findOne(id);
    
    // Business logic: Check name conflict if updating name
    if (updateRestaurantDto.name && updateRestaurantDto.name !== restaurant.name) {
      const existingRestaurant = await this.restaurantRepository.findByName(updateRestaurantDto.name);
      if (existingRestaurant) {
        throw new ConflictException(`Nhà hàng với tên "${updateRestaurantDto.name}" đã tồn tại`);
      }
    }
    
    return await this.restaurantRepository.update(id, updateRestaurantDto);
  }

  async remove(id: string): Promise<void> {
    await this.findOne(id); // Check if exists
    await this.restaurantRepository.delete(id);
  }

  async findByStatus(status: string): Promise<Restaurant[]> {
    return await this.restaurantRepository.findByStatus(status as any);
  }
}