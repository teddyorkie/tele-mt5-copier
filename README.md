# tele-mt5-copier (Giai đoạn 1: Signal Textbox -> MT5 Auto Limit & Trade Manager)

Ứng dụng đọc tin nhắn tín hiệu Forex/Gold, giải mã vùng Entry và các mốc TP viết tắt 2 chữ số, tự động đặt 2 lệnh chờ Limit trên **MetaTrader 5 (MT5)** và quản lý lệnh theo bộ quy tắc chiến lược.

## Tính năng Giai đoạn 1
1. **Giải mã tín hiệu thông minh (`src/parser.py`)**:
   - Hỗ trợ tin nhắn chứa đồng thời nhiều kèo (`SELL GOLD` và `BUY GOLD`), tự lọc bỏ emoji (`🍀🍀`).
   - Tự động quy đổi **TP viết tắt 2 chữ số** vượt mốc tròn trăm (`SELL 3908 ... TP 98 76` -> `3898`, `3876`; `BUY 3881 ... TP 92 15` -> `3892`, `3915`).
2. **Chiến lược chia 2 lệnh & Vào sớm (`src/planner.py`)**:
   - Chia khối lượng thành 2 lệnh Limit (`0.01` lot/lệnh) tại 2 điểm Entry.
   - Bù giá vào sớm (`early_entry_offset`, mặc định `0.5` giá: cộng thêm cho BUY, trừ đi cho SELL).
   - **Chặn lệnh khi giá đã trong vùng Entry**: Nếu giá `Bid/Ask` hiện tại đã chạm hoặc nằm sẵn trong vùng Entry, hệ thống **không đặt lệnh** và phát cảnh báo ngay trên giao diện.
3. **Quản lý lệnh tự động (`src/trade_manager.py`)**:
   - **Quy tắc +6 giá (Break Even)**: Khi vị thế đang mở đạt lợi nhuận `+6.0` giá, tự động dời `SL` về đúng giá `Entry`.
   - **Tự hủy lệnh chờ sau 4 tiếng**: Tự động xóa các lệnh Limit chưa khớp sau `4 giờ`.
4. **Kiến trúc sẵn sàng cho Giai đoạn 2 (`src/service.py`)**:
   - Toàn bộ lõi xử lý được đóng gói qua `CopierService` và `EventListener`. Khi sang Giai đoạn 2, module Telegram Userbot chỉ cần gọi `service.process_message()` và đăng ký nhận sự kiện qua `service.subscribe()` mà không cần sửa lại bất kỳ dòng code nào của Giai đoạn 1.

## Cài đặt & Chạy chương trình (Dùng `uv`)

```powershell
cd E:\proj\tele-mt5-copier
uv sync
uv run python main.py
```

*(Thêm thư viện mới bằng lệnh: `uv add <ten-thu-vien>`)*

## Chạy Kiểm thử Tự động (Unit Tests)

```powershell
uv run pytest -v
```
