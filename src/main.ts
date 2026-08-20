import { NestFactory } from '@nestjs/core';
import { ConfigService } from '@nestjs/config';
import type { Server } from 'http';
import { AppModule } from './app.module';
import type { Env } from './config/env.schema';
import { MediaStreamGateway } from './telephony/media-stream.gateway';

async function bootstrap() {
  const app = await NestFactory.create(AppModule);

  // Runs PrismaService.onModuleDestroy and MediaStreamGateway's socket teardown
  // on SIGTERM/SIGINT, so connections close cleanly instead of being dropped.
  app.enableShutdownHooks();

  const config = app.get<ConfigService<Env, true>>(ConfigService);
  await app.listen(config.get('PORT', { infer: true }));

  // Twilio's media stream shares this HTTP server, so the gateway can only be
  // wired up here — it is the one place that holds the server instance.
  app.get(MediaStreamGateway).attach(app.getHttpServer() as Server);
}

void bootstrap();
