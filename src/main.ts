import { NestFactory } from '@nestjs/core';
import { ConfigService } from '@nestjs/config';
import type { LogLevel } from '@nestjs/common';
import type { NestExpressApplication } from '@nestjs/platform-express';
import { join } from 'path';
import { AppModule } from './app.module';
import type { Env } from './config/env.schema';
import {
  DEV_ASSETS_PREFIX,
  isDevClientEnabled,
} from './dev/dev-client.enabled';
import { MediaStreamGateway } from './telephony/media-stream.gateway';

/**
 * Transcripts are personal data, and from Phase 2 they are logged at `debug`.
 *
 * Nest's default enables every level, which would make "debug only" a comment
 * rather than a control — the caller's words would go to the production log in
 * full. Silencing `debug` and `verbose` outside development is what makes the
 * distinction real. Phase 6 owns retention for the stored rows.
 */
function logLevels(): LogLevel[] {
  const base: LogLevel[] = ['log', 'warn', 'error', 'fatal'];

  return process.env.NODE_ENV === 'production'
    ? base
    : [...base, 'debug', 'verbose'];
}

async function bootstrap() {
  const app = await NestFactory.create<NestExpressApplication>(AppModule, {
    logger: logLevels(),
  });

  // Same gate as the DevModule import in app.module.ts. Gating only the module
  // would leave the bundle served in production: /dev would 404 while
  // /dev/assets/main.js carried on answering.
  if (isDevClientEnabled()) {
    // A prefix distinct from the controller's own routes, so the static
    // middleware and the router cannot shadow one another.
    app.useStaticAssets(join(process.cwd(), 'public', 'assets'), {
      prefix: DEV_ASSETS_PREFIX,
    });
  }

  // Runs PrismaService.onModuleDestroy and MediaStreamGateway's socket teardown
  // on SIGTERM/SIGINT, so connections close cleanly instead of being dropped.
  app.enableShutdownHooks();

  const config = app.get<ConfigService<Env, true>>(ConfigService);
  await app.listen(config.get('PORT', { infer: true }));

  // Twilio's media stream shares this HTTP server, so the gateway can only be
  // wired up here — it is the one place that holds the server instance.
  app.get(MediaStreamGateway).attach(app.getHttpServer());
}

void bootstrap();
