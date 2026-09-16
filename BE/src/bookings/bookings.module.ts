import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { BookingsService } from './bookings.service';
import { BookingsController } from './bookings.controller';
import { Booking } from './entities/booking.entity';
import { BookingRepository } from './booking.repository';
import { RestaurantsModule } from '../restaurants/restaurants.module';
import { BranchesModule } from '../branches/branches.module';

@Module({
  imports: [
    TypeOrmModule.forFeature([Booking]),
    RestaurantsModule, // Import để sử dụng RestaurantsService
    BranchesModule,   // Import để sử dụng BranchesService
  ],
  controllers: [BookingsController],
  providers: [BookingsService, BookingRepository],
  exports: [BookingsService, BookingRepository],
})
export class BookingsModule {}