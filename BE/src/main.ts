import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';
import { Logger, ValidationPipe } from '@nestjs/common';
import { DocumentBuilder, SwaggerModule } from '@nestjs/swagger';

async function bootstrap() {
  const app = await NestFactory.create(AppModule);
  
  // Enable logging
  app.useLogger(new Logger());
  
  // Enable CORS — CORS_ORIGIN nhận 1 origin, hoặc nhiều origin ngăn cách bởi dấu phẩy
  const corsOrigins = (process.env.CORS_ORIGIN ?? '*')
    .split(',')
    .map((origin) => origin.trim())
    .filter(Boolean);
  app.enableCors({
    origin: corsOrigins.length === 1 ? corsOrigins[0] : corsOrigins,
    credentials: true,
    methods: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
    allowedHeaders: ['Content-Type', 'Authorization'],
  });
  
  // Global validation pipe
  app.useGlobalPipes(new ValidationPipe({
    whitelist: true,
    forbidNonWhitelisted: true,
    transform: true,
    forbidUnknownValues: false,
    skipMissingProperties: false,
  }));

  // Swagger configuration
  const config = new DocumentBuilder()
    .setTitle('Restaurant AI API')
    .setDescription('API quản lý nhà hàng với AI')
    .setVersion('1.0')
    .addTag('Restaurants')
    .addTag('Branches')
    .addTag('Bookings')
    .addTag('Calls')
    .build();
  
  const document = SwaggerModule.createDocument(app, config);
  SwaggerModule.setup('api-docs', app, document);
  
  const port = process.env.PORT ?? 8070;
  await app.listen(port);
  Logger.log(`Ứng dụng đang chạy tại: http://localhost:${port}`, 'Bootstrap');
  Logger.log(`Swagger API docs: http://localhost:${port}/api-docs`, 'Bootstrap');
}
bootstrap();
