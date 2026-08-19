import { Controller, Get, ServiceUnavailableException } from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service';
import { withTimeout } from '../common/with-timeout';

/** A stopped container does not refuse connections quickly — bound the wait. */
const DB_PING_TIMEOUT_MS = 2000;

interface HealthResponse {
  status: 'ok';
  database: 'up';
}

@Controller('health')
export class HealthController {
  constructor(private readonly prisma: PrismaService) {}

  @Get()
  async check(): Promise<HealthResponse> {
    if (!(await this.isDatabaseUp())) {
      // 503 rather than 200-with-a-down-body: a monitor that only reads the
      // status code must still see the failure.
      throw new ServiceUnavailableException({
        status: 'error',
        database: 'down',
      });
    }

    return { status: 'ok', database: 'up' };
  }

  private async isDatabaseUp(): Promise<boolean> {
    try {
      await withTimeout(
        this.prisma.$queryRaw`SELECT 1`,
        DB_PING_TIMEOUT_MS,
        'health ping',
      );
      return true;
    } catch {
      return false;
    }
  }
}
