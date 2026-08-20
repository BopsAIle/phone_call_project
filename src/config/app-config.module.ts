import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { validateEnv } from './env.schema';

/**
 * Deliberately not named `ConfigModule` — that name is taken by @nestjs/config
 * and having two of them makes every import site ambiguous.
 *
 * `isGlobal: true` registers ConfigService application-wide, so importing this
 * module once in AppModule is enough.
 */
@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      cache: true,
      validate: validateEnv,
    }),
  ],
})
export class AppConfigModule {}
