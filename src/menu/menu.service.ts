import {
  Injectable,
  NotFoundException,
  BadRequestException,
  ConflictException,
} from '@nestjs/common';
import { MenuItem, MenuItemStatus } from './entities/menu-item.entity';
import { OrderItem } from './entities/order-item.entity';
import { CreateMenuItemDto } from './dto/create-menu-item.dto';
import { CreateTakeoutBookingDto } from './dto/create-takeout-booking.dto';
import { CreateDeliveryBookingDto } from './dto/create-delivery-booking.dto';
import { MenuRepository } from './menu.repository';
import { OrderItemRepository } from './order-item.repository';
import { BookingsService } from '../bookings/bookings.service';
import { BranchesService } from '../branches/branches.service';
import { RestaurantsService } from '../restaurants/restaurants.service';
import { BookingStatus, BookingSource, ShipperStatus } from '../bookings/entities/booking.entity';
import { BranchStatus } from '../branches/entities/branch.entity';
import { RestaurantStatus } from '../restaurants/entities/restaurant.entity';
import { Booking } from '../bookings/entities/booking.entity';

@Injectable()
export class MenuService {
  constructor(
    private readonly menuRepository: MenuRepository,
    private readonly orderItemRepository: OrderItemRepository,
    private readonly bookingsService: BookingsService,
    private readonly branchesService: BranchesService,
    private readonly restaurantsService: RestaurantsService,
  ) {}

  async createMenuItem(createMenuItemDto: CreateMenuItemDto): Promise<MenuItem> {
    // Validate branch exists
    const branch = await this.branchesService.findOne(createMenuItemDto.branch_id);
    if (!branch) {
      throw new NotFoundException('Chi nhánh không được tìm thấy');
    }

    return await this.menuRepository.create({
      branch_id: createMenuItemDto.branch_id,
      name: createMenuItemDto.name,
      description: createMenuItemDto.description,
      price: createMenuItemDto.price,
      status: createMenuItemDto.status || MenuItemStatus.AVAILABLE,
      quantity_available: createMenuItemDto.quantity_available || 1000,
    });
  }

  async getMenuByBranchId(branchId: string): Promise<MenuItem[]> {
    const branch = await this.branchesService.findOne(branchId);
    if (!branch) {
      throw new NotFoundException('Chi nhánh không được tìm thấy');
    }

    return await this.menuRepository.findByBranchId(branchId);
  }

  async getMenuItem(id: string): Promise<MenuItem> {
    const menuItem = await this.menuRepository.findById(id);
    if (!menuItem) {
      throw new NotFoundException('Không tìm thấy menu item');
    }
    return menuItem;
  }

  async updateMenuItem(id: string, updateData: Partial<MenuItem>): Promise<MenuItem | null> {
    const menuItem = await this.getMenuItem(id);
    return await this.menuRepository.update(id, updateData);
  }

  async deleteMenuItem(id: string): Promise<void> {
    await this.getMenuItem(id);
    await this.menuRepository.delete(id);
  }

  async createTakeoutBooking(
    createTakeoutBookingDto: CreateTakeoutBookingDto,
  ): Promise<Booking & { order_items: OrderItem[] }> {
    // Validate nhà hàng tồn tại và hoạt động
    const restaurant = await this.restaurantsService.findOne(
      createTakeoutBookingDto.restaurant_id,
    );
    if (restaurant.status !== RestaurantStatus.ACTIVE) {
      throw new BadRequestException('Nhà hàng hiện không hoạt động');
    }

    // Validate chi nhánh tồn tại và hoạt động
    const branch = await this.branchesService.findOne(createTakeoutBookingDto.branch_id);
    if (branch.status !== BranchStatus.ACTIVE) {
      throw new BadRequestException('Chi nhánh hiện không hoạt động');
    }

    // Validate chi nhánh thuộc nhà hàng
    if (branch.restaurant_id !== createTakeoutBookingDto.restaurant_id) {
      throw new BadRequestException('Chi nhánh không thuộc về nhà hàng được chọn');
    }

    // Validate ngày đặt hàng
    const bookingDate = new Date(createTakeoutBookingDto.booking_date);
    bookingDate.setHours(0, 0, 0, 0);

    const today = new Date();
    today.setHours(0, 0, 0, 0);

    if (bookingDate < today) {
      throw new BadRequestException('Không thể đặt hàng cho ngày trong quá khứ');
    }

    const maxDate = new Date();
    maxDate.setMonth(maxDate.getMonth() + 3);
    maxDate.setHours(0, 0, 0, 0);

    if (bookingDate > maxDate) {
      throw new BadRequestException('Chỉ có thể đặt hàng trong vòng 3 tháng tới');
    }

    // Validate giờ mở cửa chi nhánh
    if (branch.opening_time && branch.closing_time) {
      if (
        createTakeoutBookingDto.booking_time < branch.opening_time ||
        createTakeoutBookingDto.booking_time > branch.closing_time
      ) {
        throw new BadRequestException(
          `Chi nhánh chỉ mở cửa từ ${branch.opening_time} đến ${branch.closing_time}`,
        );
      }
    }

    // Validate items
    if (!createTakeoutBookingDto.items || createTakeoutBookingDto.items.length === 0) {
      throw new BadRequestException('Phải có ít nhất 1 item trong đơn hàng');
    }

    const menuItemIds = createTakeoutBookingDto.items.map((item) => item.menu_item_id);
    const menuItems = await this.menuRepository.findByBranchAndIds(
      createTakeoutBookingDto.branch_id,
      menuItemIds,
    );

    if (menuItems.length !== menuItemIds.length) {
      throw new NotFoundException(
        `Một số menu item không được tìm thấy hoặc không thuộc chi nhánh này`,
      );
    }

    // Kiểm tra item có sẵn và tính tổng giá
    let totalPrice = 0;
    const itemMap = new Map(menuItems.map((item) => [item.id, item]));

    for (const item of createTakeoutBookingDto.items) {
      const menuItem = itemMap.get(item.menu_item_id);

      if (!menuItem) {
        throw new NotFoundException(
          `Menu item ${item.menu_item_id} không được tìm thấy hoặc không thuộc chi nhánh này`,
        );
      }

      if (menuItem.status !== MenuItemStatus.AVAILABLE) {
        throw new BadRequestException(
          `"${menuItem.name}" hiện không khả dụng (trạng thái: ${menuItem.status})`,
        );
      }

      if (menuItem.quantity_available < item.quantity) {
        throw new BadRequestException(
          `"${menuItem.name}" chỉ còn ${menuItem.quantity_available} phần, bạn yêu cầu ${item.quantity}`,
        );
      }

      totalPrice += menuItem.price * item.quantity;
    }

    // Tạo booking với booking_type = TAKEOUT
    const bookingData: any = {
      restaurant_id: createTakeoutBookingDto.restaurant_id,
      branch_id: createTakeoutBookingDto.branch_id,
      customer_name: createTakeoutBookingDto.customer_name,
      phone_number: createTakeoutBookingDto.customer_phone,
      booking_date: bookingDate,
      booking_time: createTakeoutBookingDto.booking_time,
      booking_type: 'takeout',
      party_size: 0,
      total_price: totalPrice,
      note: createTakeoutBookingDto.note || 'Đặt hàng mang về qua AI voice',
      source: BookingSource.PHONE_AI,
      status: BookingStatus.PENDING,
    };

    const booking = await this.bookingsService.createFromDto(bookingData);

    // Tạo order items
    const orderItemsData: Partial<OrderItem>[] = createTakeoutBookingDto.items.map(
      (item) => {
        const menuItem = itemMap.get(item.menu_item_id);
        if (!menuItem) {
          throw new NotFoundException(`Menu item ${item.menu_item_id} không được tìm thấy`);
        }
        return {
          booking_id: booking.id,
          menu_item_id: item.menu_item_id,
          quantity: item.quantity,
          unit_price: menuItem.price,
          subtotal: menuItem.price * item.quantity,
        };
      },
    );

    const orderItems = await this.orderItemRepository.createMultiple(orderItemsData);

    return {
      ...booking,
      order_items: orderItems,
    };
  }

  async getOrderItems(bookingId: string): Promise<OrderItem[]> {
    return await this.orderItemRepository.findByBookingId(bookingId);
  }

  async confirmTakeoutBooking(bookingId: string): Promise<any> {
    // Lấy booking
    const booking = await this.bookingsService.findOne(bookingId);
    
    if ((booking as any).booking_type !== 'takeout') {
      throw new BadRequestException('Chỉ có thể confirm đơn TAKEOUT');
    }

    if (booking.status !== BookingStatus.PENDING) {
      throw new BadRequestException(`Không thể confirm booking có trạng thái ${booking.status}`);
    }

    // Lấy order items
    const orderItems = await this.orderItemRepository.findByBookingId(bookingId);

    if (!orderItems || orderItems.length === 0) {
      throw new BadRequestException('Không tìm thấy items trong đơn hàng');
    }

    // Trừ kho cho từng item
    for (const orderItem of orderItems) {
      const menuItem = await this.menuRepository.findById(orderItem.menu_item_id);
      
      if (!menuItem) {
        throw new NotFoundException(
          `Menu item ${orderItem.menu_item_id} không được tìm thấy`,
        );
      }

      const newQuantity = menuItem.quantity_available - orderItem.quantity;
      
      if (newQuantity < 0) {
        throw new BadRequestException(
          `${menuItem.name} không đủ hàng. Hiện tại còn ${menuItem.quantity_available}, yêu cầu ${orderItem.quantity}`,
        );
      }

      await this.menuRepository.update(orderItem.menu_item_id, {
        quantity_available: newQuantity,
      });
    }

    // Update booking status thành CONFIRMED
    const updatedBooking = await this.bookingsService.update(bookingId, {
      status: BookingStatus.CONFIRMED,
    });

    return {
      message: 'Xác nhận đơn mang về thành công, kho hàng đã được cập nhật',
      booking: updatedBooking,
      order_items: orderItems,
    };
  }

  // ===== DELIVERY METHODS =====

  async createDeliveryBooking(
    createDeliveryBookingDto: CreateDeliveryBookingDto,
  ): Promise<Booking & { order_items: OrderItem[] }> {
    // Validate nhà hàng tồn tại và hoạt động
    const restaurant = await this.restaurantsService.findOne(
      createDeliveryBookingDto.restaurant_id,
    );
    if (restaurant.status !== RestaurantStatus.ACTIVE) {
      throw new BadRequestException('Nhà hàng hiện không hoạt động');
    }

    // Validate chi nhánh tồn tại và hoạt động
    const branch = await this.branchesService.findOne(createDeliveryBookingDto.branch_id);
    if (branch.status !== BranchStatus.ACTIVE) {
      throw new BadRequestException('Chi nhánh hiện không hoạt động');
    }

    // Validate chi nhánh thuộc nhà hàng
    if (branch.restaurant_id !== createDeliveryBookingDto.restaurant_id) {
      throw new BadRequestException('Chi nhánh không thuộc về nhà hàng được chọn');
    }

    // Validate ngày đặt hàng
    const bookingDate = new Date(createDeliveryBookingDto.booking_date);
    bookingDate.setHours(0, 0, 0, 0);

    const today = new Date();
    today.setHours(0, 0, 0, 0);

    if (bookingDate < today) {
      throw new BadRequestException('Không thể đặt hàng cho ngày trong quá khứ');
    }

    const maxDate = new Date();
    maxDate.setMonth(maxDate.getMonth() + 3);
    maxDate.setHours(0, 0, 0, 0);

    if (bookingDate > maxDate) {
      throw new BadRequestException('Chỉ có thể đặt hàng trong vòng 3 tháng tới');
    }

    // Validate giờ mở cửa chi nhánh
    if (branch.opening_time && branch.closing_time) {
      if (
        createDeliveryBookingDto.booking_time < branch.opening_time ||
        createDeliveryBookingDto.booking_time > branch.closing_time
      ) {
        throw new BadRequestException(
          `Chi nhánh chỉ mở cửa từ ${branch.opening_time} đến ${branch.closing_time}`,
        );
      }
    }

    // Validate items
    if (!createDeliveryBookingDto.items || createDeliveryBookingDto.items.length === 0) {
      throw new BadRequestException('Phải có ít nhất 1 item trong đơn hàng');
    }

    const menuItemIds = createDeliveryBookingDto.items.map((item) => item.menu_item_id);
    const menuItems = await this.menuRepository.findByBranchAndIds(
      createDeliveryBookingDto.branch_id,
      menuItemIds,
    );

    if (menuItems.length !== menuItemIds.length) {
      throw new NotFoundException(
        `Một số menu item không được tìm thấy hoặc không thuộc chi nhánh này`,
      );
    }

    // Kiểm tra item có sẵn và tính tổng giá (bao gồm phí giao)
    let totalPrice = 0;
    const itemMap = new Map(menuItems.map((item) => [item.id, item]));

    for (const item of createDeliveryBookingDto.items) {
      const menuItem = itemMap.get(item.menu_item_id);

      if (!menuItem) {
        throw new NotFoundException(
          `Menu item ${item.menu_item_id} không được tìm thấy hoặc không thuộc chi nhánh này`,
        );
      }

      if (menuItem.status !== MenuItemStatus.AVAILABLE) {
        throw new BadRequestException(
          `"${menuItem.name}" hiện không khả dụng (trạng thái: ${menuItem.status})`,
        );
      }

      if (menuItem.quantity_available < item.quantity) {
        throw new BadRequestException(
          `"${menuItem.name}" chỉ còn ${menuItem.quantity_available} phần, bạn yêu cầu ${item.quantity}`,
        );
      }

      totalPrice += menuItem.price * item.quantity;
    }

    // Thêm phí giao hàng vào total price
    totalPrice += createDeliveryBookingDto.delivery_fee;

    // Tạo booking với booking_type = DELIVERY
    const bookingData: any = {
      restaurant_id: createDeliveryBookingDto.restaurant_id,
      branch_id: createDeliveryBookingDto.branch_id,
      customer_name: createDeliveryBookingDto.customer_name,
      phone_number: createDeliveryBookingDto.customer_phone,
      booking_date: bookingDate,
      booking_time: createDeliveryBookingDto.booking_time,
      booking_type: 'delivery',
      party_size: 0,
      total_price: totalPrice,
      note: createDeliveryBookingDto.note || 'Đặt hàng giao hàng qua AI voice',
      source: BookingSource.PHONE_AI,
      status: BookingStatus.PENDING,
      // Delivery fields
      delivery_address: createDeliveryBookingDto.delivery_address,
      delivery_phone: createDeliveryBookingDto.delivery_phone || createDeliveryBookingDto.customer_phone,
      delivery_fee: createDeliveryBookingDto.delivery_fee,
      estimated_delivery_time: createDeliveryBookingDto.estimated_delivery_time,
      shipper_status: ShipperStatus.PENDING,
    };

    const booking = await this.bookingsService.createFromDto(bookingData);

    // Tạo order items
    const orderItemsData: Partial<OrderItem>[] = createDeliveryBookingDto.items.map(
      (item) => {
        const menuItem = itemMap.get(item.menu_item_id);
        if (!menuItem) {
          throw new NotFoundException(`Menu item ${item.menu_item_id} không được tìm thấy`);
        }
        return {
          booking_id: booking.id,
          menu_item_id: item.menu_item_id,
          quantity: item.quantity,
          unit_price: menuItem.price,
          subtotal: menuItem.price * item.quantity,
        };
      },
    );

    const orderItems = await this.orderItemRepository.createMultiple(orderItemsData);

    return {
      ...booking,
      order_items: orderItems,
    };
  }

  async confirmDeliveryBooking(bookingId: string): Promise<any> {
    // Lấy booking
    const booking = await this.bookingsService.findOne(bookingId);
    
    if ((booking as any).booking_type !== 'delivery') {
      throw new BadRequestException('Chỉ có thể confirm đơn DELIVERY');
    }

    if (booking.status !== BookingStatus.PENDING) {
      throw new BadRequestException(`Không thể confirm booking có trạng thái ${booking.status}`);
    }

    // Lấy order items
    const orderItems = await this.orderItemRepository.findByBookingId(bookingId);

    if (!orderItems || orderItems.length === 0) {
      throw new BadRequestException('Không tìm thấy items trong đơn hàng');
    }

    // Trừ kho cho từng item
    for (const orderItem of orderItems) {
      const menuItem = await this.menuRepository.findById(orderItem.menu_item_id);
      
      if (!menuItem) {
        throw new NotFoundException(
          `Menu item ${orderItem.menu_item_id} không được tìm thấy`,
        );
      }

      const newQuantity = menuItem.quantity_available - orderItem.quantity;
      
      if (newQuantity < 0) {
        throw new BadRequestException(
          `${menuItem.name} không đủ hàng. Hiện tại còn ${menuItem.quantity_available}, yêu cầu ${orderItem.quantity}`,
        );
      }

      await this.menuRepository.update(orderItem.menu_item_id, {
        quantity_available: newQuantity,
      });
    }

    // Update booking status thành CONFIRMED, shipper_status thành ASSIGNED
    const updatedBooking = await this.bookingsService.update(bookingId, {
      status: BookingStatus.CONFIRMED,
      shipper_status: ShipperStatus.ASSIGNED,
    });

    return {
      message: 'Xác nhận đơn giao hàng thành công, kho hàng đã được cập nhật',
      booking: updatedBooking,
      order_items: orderItems,
    };
  }

}
