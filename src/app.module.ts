import { Module } from '@nestjs/common';
import { AppConfigModule } from './config/app-config.module';
import { DevModule } from './dev/dev.module';
import { isDevClientEnabled } from './dev/dev-client.enabled';
import { HealthModule } from './health/health.module';
import { PrismaModule } from './prisma/prisma.module';
import { TelephonyModule } from './telephony/telephony.module';

@Module({
  imports: [
    AppConfigModule,
    PrismaModule,
    HealthModule,
    TelephonyModule,
    // The dev client exposes a microphone-capture page and the store number, so
    // outside development it must not be registered at all. This runs while the
    // module graph is built, before DI exists, which is why the check reads
    // process.env directly — main.ts gates its static assets on the same call.
    ...(isDevClientEnabled() ? [DevModule] : []),
  ],
})
export class AppModule {}
