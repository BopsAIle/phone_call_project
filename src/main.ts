import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';
import { Logger } from '@nestjs/common';

async function bootstrap() {
  const app = await NestFactory.create(AppModule);
  
  // Enable logging
  app.useLogger(new Logger());
  
  const port = process.env.PORT ?? 8080;
  await app.listen(port);
  
  Logger.log(`Ứng dụng đang chạy tại: http://localhost:${port}`, 'Bootstrap');
}
bootstrap();
