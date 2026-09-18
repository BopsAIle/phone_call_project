# 16 — Frontend dashboard

Thư mục `FE/`. Cổng **3070**. http://localhost:3070

## Đây là gì

Một dashboard quản trị cho nhân viên nhà hàng: xem và sửa nhà hàng, chi nhánh, thực đơn,
đơn đặt bàn, đơn món. **Không liên quan gì tới thoại** — nó chỉ nói chuyện với BE.

Stack: React 18 + Vite 5 + TypeScript + **Ant Design 5** + **TanStack Query** +
React Router + axios. Giao diện tiếng Việt (`locale={viVN}`).

## Cấu trúc

```
FE/src/
├── main.tsx            điểm vào
├── App.tsx             QueryClient + ConfigProvider (theme) + Router
├── api/
│   ├── axios.ts        instance axios, baseURL = VITE_API_URL
│   ├── restaurants.ts  bookings.ts  branches.ts  menu.ts
│   └── index.ts
├── hooks/              useRestaurants, useBranches, useBookings, useMenu
├── pages/
│   ├── Dashboard.tsx
│   ├── Restaurants/    List, Form, Detail
│   ├── Branches/       List, Form
│   ├── Menu/           List, Form
│   ├── Bookings/       List, Form
│   └── Orders/         List, OrderForm, TakeoutForm, DeliveryForm
├── components/         MainLayout, LoadingSpinner
├── types/              kiểu TS khớp entity của BE
└── utils/              formatPrice, constants
```

## Điều hướng

`App.tsx` dùng **`HashRouter`** (URL có dấu `#`). Hash router không cần server cấu hình
fallback về `index.html` — tiện khi host tĩnh hoặc chạy sau tunnel.

Menu bên trái (`MainLayout.tsx`):

| Route | Trang |
| --- | --- |
| `/` | Dashboard |
| `/restaurants` | Nhà hàng |
| `/branches` | Chi nhánh |
| `/menu` | Thực đơn |
| `/orders` | Đơn hàng |
| `/bookings` | Đặt bàn |

## Gọi API: ba tầng rõ ràng

```
component  →  hook (react-query)  →  api/*.ts (axios)  →  BE
```

**Tầng api** bóc lớp bọc của BE:

```typescript
interface ApiResponse<T> { success: boolean; message: string; data: T; ... }

getAll: async (status?) => {
  const response = await axiosInstance.get<ApiResponse<Restaurant[]>>('/restaurants', { params: { status } })
  return response.data.data        // ← bóc hai lớp: axios .data, rồi ApiResponse .data
}
```

**Tầng hook** lo cache, loading, và làm mới sau khi ghi:

```typescript
export const useCreateRestaurant = () => {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: restaurantApi.create,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['restaurants'] }),
  })
}
```

Component chỉ việc `const { data, isLoading } = useRestaurants()`.

## Proxy — vì sao `VITE_API_URL=/api`

```typescript
// FE/vite.config.ts
server: {
  port: 3070,
  strictPort: true,
  allowedHosts: ['.jupiter-ai.pro', 'callphone.jupiter-ai.pro'],
  proxy: {
    '/api': { target: 'http://localhost:8070', changeOrigin: true,
               rewrite: (path) => path.replace(/^\/api/, '') }
  }
}
```

Trình duyệt gọi `/api/restaurants` (**cùng origin**) → Vite chuyển tiếp thành
`http://localhost:8070/restaurants`. Hai lợi ích: **không cần CORS**, và trang mở qua
tunnel vẫn chạy đúng.

Nếu để URL tuyệt đối `http://localhost:8070`, người truy cập từ xa sẽ gọi vào **máy của
chính họ** — và không hiểu vì sao trắng trang.

### Ba cái bẫy trong config này

1. **`FE/vite.config.js` tồn tại song song với `.ts`**, là bản do `tsc -b` sinh ra. Và
   **Vite nạp `.js` trước `.ts`**. Sửa mỗi file `.ts` sẽ không có tác dụng — phải sửa cả hai.
2. **`strictPort: true`** bắt buộc. Không có nó, Vite tự nhảy sang cổng kế tiếp khi 3070
   bận, và đã từng đè lên cổng của NestJS gây `EADDRINUSE`.
3. **`allowedHosts`** cần cho tunnel. Vite 5 chặn Host lạ để chống DNS-rebinding; thiếu
   khai báo sẽ báo `Blocked request. This host ("...") is not allowed`. Tiền tố `.` khớp cả
   domain gốc lẫn mọi subdomain.

## Đơn hàng: ba form

`pages/Orders/` có `OrderForm`, `TakeoutForm`, `DeliveryForm` — phản chiếu đúng ba loại
`booking_type` bên BE (`DINE_IN` / `TAKEOUT` / `DELIVERY`). Đơn do AI tạo cũng hiện ở đây,
phân biệt bằng cột `source = PHONE_AI`.

## ⚠️ Không có đăng nhập

Dashboard **không có màn hình đăng nhập**. Cộng với việc BE không có guard, ai mở được
trang là sửa được dữ liệu. Chi tiết và cách phòng: [chương 15](15-backend-nestjs.md).

## Chạy

```bash
cd FE && npm install && npm run dev     # http://localhost:3070
npm run build                            # tsc -b && vite build
```

## Đừng nhầm với `AI/frontend/`

`AI/frontend/` là **một app khác hẳn**: UI demo thu âm bằng TypeScript thuần (không
React), chạy cổng 5173, nói WebSocket với AI Bridge. Xem
[chương 03](03-chay-thu-lan-dau.md).

## Tiếp theo

→ [17 — Log, đo lường, ghi âm](17-log-do-luong-ghi-am.md)
