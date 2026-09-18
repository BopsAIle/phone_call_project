import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { CallsService } from './calls.service';
import { CallsController } from './calls.controller';
import { CallRepository } from './call.repository';
import { Call } from './entities/call.entity';
import { CallMessage } from './entities/call-message.entity';

@Module({
  imports: [TypeOrmModule.forFeature([Call, CallMessage])],
  controllers: [CallsController],
  providers: [CallsService, CallRepository],
  exports: [CallsService, CallRepository],
})
export class CallsModule {}
