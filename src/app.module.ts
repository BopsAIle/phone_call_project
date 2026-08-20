import { Module } from '@nestjs/common';
import { AppConfigModule } from './config/app-config.module';
import { HealthModule } from './health/health.module';
import { PrismaModule } from './prisma/prisma.module';
import { TelephonyModule } from './telephony/telephony.module';

@Module({
  imports: [AppConfigModule, PrismaModule, HealthModule, TelephonyModule],
})
export class AppModule {}
