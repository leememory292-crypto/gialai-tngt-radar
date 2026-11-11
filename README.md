# 🚨 Gia Lai Traffic Accident Radar (TNGT)

Hệ thống tự động thu thập, phân tích và gửi cảnh báo sớm thông tin **Tai nạn giao thông (TNGT)** trên các tuyến Quốc lộ, Đường tỉnh và địa bàn tỉnh **Gia Lai** qua **GitHub Actions** về **Google Groups (`tngt@googlegroups.com`)**.

---

## 1. Thông số vận hành cốt lõi (Core Operational Parameters)

| Thông số | Giá trị cấu hình |
| :--- | :--- |
| **Email gửi (Sender)** | `leememory292@gmail.com` (xác thực qua Gmail SMTP & App Password) |
| **Nhóm nhận cảnh báo (Recipient)** | `tngt@googlegroups.com` |
| **Khung giờ quét tự động** | Mỗi **2 giờ/lần** từ **06:00 đến 21:00 (Giờ Việt Nam - GMT+7)** |
| **Biểu thức Cron (UTC)** | `0 23,1,3,5,7,9,11,13,14 * * *` (tương ứng 06h, 08h, 10h, 12h, 14h, 16h, 18h, 20h, 21h VN) |
| **Lưu trữ trạng thái & Chống trùng** | `data/history.json` (tự động commit sau mỗi lần chạy, giới hạn 500 URL gần nhất) |
| **Độ tươi dữ liệu (Freshness)** | Chỉ đánh giá các bài báo xuất bản trong vòng **48 giờ** gần nhất |

---

## 2. Cấu trúc thư mục dự án

```text
gialai-tngt-radar/
├── .github/
│   └── workflows/
│       └── tngt_radar.yml     # Cấu hình GitHub Actions chạy định kỳ & thủ công
├── data/
│   └── history.json           # Lưu danh sách scraped_urls để chống gửi trùng
├── scripts/
│   └── radar_tngt.py          # Script Python thu thập, lọc 2 tầng và gửi email HTML
├── requirements.txt           # Các thư viện phụ thuộc (requests, beautifulsoup4)
└── README.md                  # Tài liệu hướng dẫn cấu hình & vận hành
```

---

## 3. Logic lọc 2 tầng (Two-Tier Intersection Filtering)

Một bài báo chỉ được kích hoạt gửi cảnh báo khi thỏa mãn đồng thời điều kiện giao (**AND**):

$$\text{Cảnh báo} = (\ge 1 \text{ Từ khóa Biến cố TNGT}) \land \big((\ge 1 \text{ Tuyến đường chỉ định}) \lor (\ge 1 \text{ Địa danh Gia Lai})\big)$$

### Tầng 1 — Từ khóa biến cố TNGT (Incident Keywords)
`tai nạn`, `tai nạn giao thông`, `tông nhau`, `va chạm`, `lật xe`, `tử vong`, `bị thương`, `chết`, `xảy ra tai nạn`, `hiện trường`, `xe máy đối đầu`, `ô tô đâm`.

### Tầng 2A — Tuyến đường bắt buộc theo dõi (Designated Routes)
- **Quốc lộ & Trục chính:** `QL19`, `QL 19`, `Quốc lộ 19`, `Đường Hồ Chí Minh`, `QL14`, `QL 14`, `Trường Sơn Đông`, `Trường Sơn đông`, `QL25`, `QL 25`, `Quốc lộ 25`, `QL19D`, `QL 19D`
- **Đường tránh đô thị:** `đường tránh Pleiku`, `tuyến tránh Pleiku`, `đường tránh Chư Sê`, `tuyến tránh Chư Sê`
- **Các tuyến đường tỉnh:** `ĐT662`, `ĐT 662`, `662B`, `662b`, `ĐT663`, `ĐT 663`, `tỉnh lộ 663`, `ĐT664`, `ĐT 664`, `tỉnh lộ 664`, `ĐT665`, `ĐT 665`, `tỉnh lộ 665`, `ĐT666`, `ĐT 666`, `tỉnh lộ 666`, `ĐT667`, `ĐT 667`, `tỉnh lộ 667`, `ĐT668`, `ĐT 668`, `tỉnh lộ 668`, `ĐT670`, `ĐT 670`, `tỉnh lộ 670`

### Tầng 2B — Địa danh hành chính tỉnh Gia Lai (Locality Anchors)
`Pleiku`, `Chư Sê`, `Chư Păh`, `Đắk Đoa` (`Đak Đoa`), `Mang Yang`, `An Khê`, `Ia Grai`, `Chư Prông`, `Đức Cơ`, `Kbang`, `Kông Chro`, `Krông Pa`, `Ayun Pa`, `Phú Thiện`, `Ia Pa`, `Chư Pưh`, `Gia Lai`.

---

## 4. Nguồn báo chí theo dõi (Target Sources)

1. **Báo Gia Lai điện tử (`baogialai.com.vn`):** Chuyên mục Pháp luật, An ninh trật tự, Thời sự, Xã hội (RSS & HTML).
2. **Cổng thông tin Công an tỉnh Gia Lai (`congan.gialai.gov.vn`):** Chuyên mục An toàn giao thông, ANTT trong tỉnh, Lực lượng CSGT, Cứu nạn cứu hộ, Thông báo.
3. **Đài PT-TH Gia Lai (`gialaitv.vn`):** Chuyên mục An ninh trật tự, An toàn giao thông & Thời sự.
4. **Báo Giao thông (`baogiaothong.vn`):** Chuyên mục An toàn giao thông, Giao thông 24h, ATGT địa phương, An ninh hình sự.

---

## 5. Hướng dẫn cấu hình GitHub Secrets & Google Groups

### Bước 1: Tạo mật khẩu ứng dụng Gmail (App Password)
1. Đăng nhập tài khoản Gmail gửi cảnh báo (`leememory292@gmail.com`).
2. Truy cập **Google Account** $\rightarrow$ **Security (Bảo mật)** $\rightarrow$ Bật **2-Step Verification (Xác minh 2 bước)**.
3. Tìm mục **App passwords (Mật khẩu ứng dụng)** $\rightarrow$ Tạo mật khẩu mới đặt tên `GitHub Actions TNGT Radar`.
4. Sao chép chuỗi mật khẩu 16 ký tự (không khoảng trắng).

### Bước 2: Khai báo GitHub Actions Secrets
1. Mở repository trên GitHub $\rightarrow$ vào tab **Settings** $\rightarrow$ **Secrets and variables** $\rightarrow$ **Actions**.
2. Nhấn **New repository secret** và thêm 2 biến sau:
   - `GMAIL_USER`: `leememory292@gmail.com`
   - `GMAIL_APP_PASSWORD`: `<Mật khẩu ứng dụng 16 ký tự>`

### Bước 3: Cho phép gửi bài vào Google Groups (`tngt@googlegroups.com`)
- Đảm bảo địa chỉ `leememory292@gmail.com` là thành viên có quyền **Post (Đăng bài)** trong nhóm `tngt@googlegroups.com`, hoặc bật quyền **Anyone on the web can post** trong phần **Group Settings $\rightarrow$ Posting policies**.

---

## 6. Kiểm thử tại máy cục bộ (Local Testing)

```bash
# Cài đặt thư viện
pip install -r requirements.txt

# 1. Chạy bộ kiểm thử tự động với dữ liệu giả lập (Mock Verification)
python scripts/radar_tngt.py --mock-test

# 2. Chạy quét thử trực tiếp 4 nguồn báo (Dry-run, không gửi mail & không ghi history.json)
python scripts/radar_tngt.py --dry-run

# 3. Kích hoạt chạy workflow trên GitHub Actions bằng GitHub CLI
gh workflow run tngt_radar.yml --ref main
```
