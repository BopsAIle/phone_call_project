import { Injectable, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { PrismaPg } from '@prisma/adapter-pg';
import { PrismaClient } from '../generated/prisma/client';
import { withTimeout } from '../common/with-timeout';
import type { Env } from '../config/env.schema';

/** Long enough for a cold container, short enough to fail visibly. */
const BOOT_PROBE_TIMEOUT_MS = 5000;

/**
 * Prisma 7 requires an explicit driver adapter — there is no implicit
 * DATABASE_URL pickup from the schema any more, because the datasource block
 * no longer carries a `url`.
 *
 * Connect strategy is fail-fast: if the database is unreachable at boot the
 * process dies, consistent with how a missing environment variable behaves.
 * The health endpoint then covers the database going away *after* a successful
 * boot, which is the case worth monitoring.
 *
 * Note that `$connect()` alone does NOT achieve this. The pg driver adapter
 * pools lazily, so it resolves happily with no database running and the app
 * boots to serve a permanently unhealthy /health. The probe query below is
 * what actually makes boot fail — verified by stopping the container.
 */
@Injectable()
export class PrismaService
  extends PrismaClient
  implements OnModuleInit, OnModuleDestroy
{
  constructor(configService: ConfigService<Env, true>) {
    super({
      adapter: new PrismaPg({
        connectionString: configService.get('DATABASE_URL', { infer: true }),
      }),
    });
  }

  async onModuleInit(): Promise<void> {
    await this.$connect();

    try {
      await withTimeout(
        this.$queryRaw`SELECT 1`,
        BOOT_PROBE_TIMEOUT_MS,
        'database probe',
      );
    } catch (cause) {
      throw new Error(
        'Cannot reach the database. Is it running? Try `npm run db:up`. ' +
          `(${cause instanceof Error ? cause.message : String(cause)})`,
        { cause },
      );
    }
  }

  /**
   * `app.enableShutdownHooks()` in main.ts is what triggers this on SIGTERM.
   * On its own it does not disconnect Prisma.
   */
  async onModuleDestroy(): Promise<void> {
    await this.$disconnect();
  }
}
