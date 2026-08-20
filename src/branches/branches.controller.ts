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
import { BranchesService } from './branches.service';
import { CreateBranchDto } from './dto/create-branch.dto';
import { UpdateBranchDto } from './dto/update-branch.dto';
import { Branch, BranchStatus } from './entities/branch.entity';

@ApiTags('Branches')
@Controller('branches')
export class BranchesController {
  constructor(private readonly branchesService: BranchesService) {}

  @Post()
  @ApiOperation({ summary: 'Tạo chi nhánh mới' })
  @ApiBody({ type: CreateBranchDto })
  @ApiResponse({
    status: 201,
    description: 'Tạo chi nhánh thành công',
    type: Branch,
  })
  @ApiResponse({
    status: 400,
    description: 'Dữ liệu không hợp lệ',
  })
  @ApiResponse({
    status: 404,
    description: 'Không tìm thấy nhà hàng',
  })
  @ApiResponse({
    status: 409,
    description: 'Tên chi nhánh đã tồn tại',
  })
  async create(@Body() createBranchDto: CreateBranchDto): Promise<Branch> {
    return await this.branchesService.create(createBranchDto);
  }

  @Get()
  @ApiOperation({ summary: 'Lấy danh sách tất cả chi nhánh' })
  @ApiQuery({
    name: 'status',
    required: false,
    enum: BranchStatus,
    description: 'Lọc theo trạng thái',
  })
  @ApiQuery({
    name: 'restaurant_id',
    required: false,
    description: 'Lọc theo ID nhà hàng',
  })
  @ApiResponse({
    status: 200,
    description: 'Danh sách chi nhánh',
    type: [Branch],
  })
  async findAll(
    @Query('status') status?: BranchStatus,
    @Query('restaurant_id') restaurantId?: string,
  ): Promise<Branch[]> {
    if (restaurantId) {
      return await this.branchesService.findByRestaurant(restaurantId);
    }
    if (status) {
      return await this.branchesService.findByStatus(status);
    }
    return await this.branchesService.findAll();
  }

  @Get(':id')
  @ApiOperation({ summary: 'Lấy thông tin chi nhánh theo ID' })
  @ApiParam({
    name: 'id',
    description: 'UUID của chi nhánh',
    example: '123e4567-e89b-12d3-a456-426614174000',
  })
  @ApiResponse({
    status: 200,
    description: 'Thông tin chi nhánh',
    type: Branch,
  })
  @ApiResponse({
    status: 404,
    description: 'Không tìm thấy chi nhánh',
  })
  async findOne(@Param('id') id: string): Promise<Branch> {
    return await this.branchesService.findOne(id);
  }

  @Patch(':id')
  @ApiOperation({ summary: 'Cập nhật thông tin chi nhánh' })
  @ApiParam({
    name: 'id',
    description: 'UUID của chi nhánh',
    example: '123e4567-e89b-12d3-a456-426614174000',
  })
  @ApiBody({ type: UpdateBranchDto })
  @ApiResponse({
    status: 200,
    description: 'Cập nhật chi nhánh thành công',
    type: Branch,
  })
  @ApiResponse({
    status: 404,
    description: 'Không tìm thấy chi nhánh',
  })
  @ApiResponse({
    status: 409,
    description: 'Tên chi nhánh đã tồn tại',
  })
  async update(
    @Param('id') id: string,
    @Body() updateBranchDto: UpdateBranchDto,
  ): Promise<Branch> {
    return await this.branchesService.update(id, updateBranchDto);
  }

  @Delete(':id')
  @ApiOperation({ summary: 'Xóa chi nhánh' })
  @ApiParam({
    name: 'id',
    description: 'UUID của chi nhánh',
    example: '123e4567-e89b-12d3-a456-426614174000',
  })
  @ApiResponse({
    status: 200,
    description: 'Xóa chi nhánh thành công',
  })
  @ApiResponse({
    status: 404,
    description: 'Không tìm thấy chi nhánh',
  })
  async remove(@Param('id') id: string): Promise<{ message: string }> {
    await this.branchesService.remove(id);
    return { message: 'Xóa chi nhánh thành công' };
  }

  @Get('restaurant/:restaurantId/count')
  @ApiOperation({ summary: 'Đếm số chi nhánh của nhà hàng' })
  @ApiParam({
    name: 'restaurantId',
    description: 'UUID của nhà hàng',
    example: '123e4567-e89b-12d3-a456-426614174000',
  })
  @ApiResponse({
    status: 200,
    description: 'Số lượng chi nhánh',
    schema: {
      type: 'object',
      properties: {
        count: { type: 'number', example: 5 },
      },
    },
  })
  async getRestaurantBranchCount(
    @Param('restaurantId') restaurantId: string,
  ): Promise<{ count: number }> {
    const count = await this.branchesService.getRestaurantBranchCount(restaurantId);
    return { count };
  }
}