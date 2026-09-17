import { Injectable } from '@nestjs/common';

@Injectable()
export class AppService {
  getHello(): string {
    return 'Chào mừng đến với NestJS có Interceptors và Exception Filters!';
  }
}
