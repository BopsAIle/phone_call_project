import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { MenuService } from './menu.service';
import { MenuController } from './menu.controller';
import { MenuItem } from './entities/menu-item.entity';
import { OrderItem } from './entities/order-item.entity';
import { MenuRepository } from './menu.repository';
import { OrderItemRepository } from './order-item.repository';
import { BookingsModule } from '../bookings/bookings.module';
import { BranchesModule } from '../branches/branches.module';
import { RestaurantsModule } from '../restaurants/restaurants.module';

@Module({
  imports: [
    TypeOrmModule.forFeature([MenuItem, OrderItem]),
    BookingsModule,
    BranchesModule,
    RestaurantsModule,
  ],
  controllers: [MenuController],
  providers: [MenuService, MenuRepository, OrderItemRepository],
  exports: [MenuService, MenuRepository, OrderItemRepository],
})
export class MenuModule {}
