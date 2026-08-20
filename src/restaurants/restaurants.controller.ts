import {
  Controller,
  Get,
  Post,
  Body,
  Patch,
  Param,
  Delete,
  Query,
} from '@nestjs/common';
import {
  ApiTags,
  ApiOperation,
  ApiResponse,
  ApiParam,
  ApiBody,
  ApiQuery,
} from '@nestjs/swagger';
import { RestaurantsService } from './restaurants.service';
import { CreateRestaurantDto } from './dto/create-restaurant.dto';
import { UpdateRestaurantDto } from './dto/update-restaurant.dto';
import { Restaurant, RestaurantStatus } from './entities/restaurant.entity';

@ApiTags('Restaurants')
@Controller('restaurants')
export class RestaurantsController {
  constructor(private readonly restaurantsService: RestaurantsService) {}

  @Post()
  @ApiOperation({ summary: 'Tạo nhà hàng mới' })
  @ApiBody({ type: CreateRestaurantDto })
  @ApiResponse({
    status: 201,
    description: 'Tạo nhà hàng thành công',
    type: Restaurant,
  })
  @ApiResponse({
    status: 400,
    description: 'Dữ liệu không hợp lệ',
  })
  @ApiResponse({
    status: 409,
    description: 'Tên nhà hàng đã tồn tại',
  })
  async create(@Body() createRestaurantDto: CreateRestaurantDto): Promise<Restaurant> {
    return await this.restaurantsService.create(createRestaurantDto);
  }

  @Get()
  @ApiOperation({ summary: 'Lấy danh sách tất cả nhà hàng' })
  @ApiQuery({
    name: 'status',
    required: false,
    enum: RestaurantStatus,
    description: 'Lọc theo trạng thái',
  })
  @ApiResponse({
    status: 200,
    description: 'Danh sách nhà hàng',
    type: [Restaurant],
  })
  async findAll(@Query('status') status?: RestaurantStatus): Promise<Restaurant[]> {
    if (status) {
      return await this.restaurantsService.findByStatus(status);
    }
    return await this.restaurantsService.findAll();
  }

  @Get(':id')
  @ApiOperation({ summary: 'Lấy thông tin nhà hàng theo ID' })
  @ApiParam({
    name: 'id',
    description: 'UUID của nhà hàng',
    example: '123e4567-e89b-12d3-a456-426614174000',
  })
  @ApiResponse({
    status: 200,
    description: 'Thông tin nhà hàng',
    type: Restaurant,
  })
  @ApiResponse({
    status: 404,
    description: 'Không tìm thấy nhà hàng',
  })
  async findOne(@Param('id') id: string): Promise<Restaurant> {
    return await this.restaurantsService.findOne(id);
  }

  @Patch(':id')
  @ApiOperation({ summary: 'Cập nhật thông tin nhà hàng' })
  @ApiParam({
    name: 'id',
    description: 'UUID của nhà hàng',
    example: '123e4567-e89b-12d3-a456-426614174000',
  })
  @ApiBody({ type: UpdateRestaurantDto })
  @ApiResponse({
    status: 200,
    description: 'Cập nhật nhà hàng thành công',
    type: Restaurant,
  })
  @ApiResponse({
    status: 404,
    description: 'Không tìm thấy nhà hàng',
  })
  @ApiResponse({
    status: 409,
    description: 'Tên nhà hàng đã tồn tại',
  })
  async update(
    @Param('id') id: string,
    @Body() updateRestaurantDto: UpdateRestaurantDto,
  ): Promise<Restaurant> {
    return await this.restaurantsService.update(id, updateRestaurantDto);
  }

  @Delete(':id')
  @ApiOperation({ summary: 'Xóa nhà hàng' })
  @ApiParam({
    name: 'id',
    description: 'UUID của nhà hàng',
    example: '123e4567-e89b-12d3-a456-426614174000',
  })
  @ApiResponse({
    status: 200,
    description: 'Xóa nhà hàng thành công',
  })
  @ApiResponse({
    status: 404,
    description: 'Không tìm thấy nhà hàng',
  })
  async remove(@Param('id') id: string): Promise<{ message: string }> {
    await this.restaurantsService.remove(id);
    return { message: 'Xóa nhà hàng thành công' };
  }
}