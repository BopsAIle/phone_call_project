import { Controller, Get, HttpException, HttpStatus } from '@nestjs/common';
import { AppService } from './app.service';

@Controller()
export class AppController {
  constructor(private readonly appService: AppService) {}

  @Get()
  getHello(): string {
    return this.appService.getHello();
  }

  @Get('success')
  getSuccess() {
    return {
      id: 1,
      name: 'Kiểm tra thành công',
      status: 'hoạt động',
    };
  }

  @Get('error')
  getError() {
    throw new HttpException('Đây là lỗi kiểm tra', HttpStatus.BAD_REQUEST);
  }

  @Get('server-error')
  getServerError() {
    throw new Error('Đây là lỗi chưa được xử lý');
  }
}
