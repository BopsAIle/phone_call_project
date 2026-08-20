import { TypeOrmModuleOptions } from '@nestjs/typeorm';

export const databaseConfig: TypeOrmModuleOptions = {
  type: 'postgres',
  host: process.env.DB_HOST || 'localhost',
  port: parseInt(process.env.DB_PORT || '5432'),
  username: process.env.DB_USERNAME || 'postgres',
  password: process.env.DB_PASSWORD || 'postgres',
  database: process.env.DB_NAME || 'restaurant_ai',
  entities: [__dirname + '/../**/*.entity{.ts,.js}'],
  synchronize: true, // Tự động tạo bảng từ entity
  autoLoadEntities: true, // Tự load entity
  logging: process.env.NODE_ENV === 'development',
};