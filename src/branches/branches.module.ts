import { Module, forwardRef } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { BranchesService } from './branches.service';
import { BranchesController } from './branches.controller';
import { Branch } from './entities/branch.entity';
import { BranchRepository } from './branch.repository';
import { RestaurantsModule } from '../restaurants/restaurants.module';

@Module({
  imports: [
    TypeOrmModule.forFeature([Branch]),
    forwardRef(() => RestaurantsModule),
  ],
  controllers: [BranchesController],
  providers: [BranchesService, BranchRepository],
  exports: [BranchesService, BranchRepository],
})
export class BranchesModule {}