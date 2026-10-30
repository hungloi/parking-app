# ===================================================================
# IMPORT CÁC THƯ VIỆN CẦN THIẾU
# ===================================================================
import cv2                                      # Xử lý hình ảnh và video từ camera
import torch                                    # Hỗ trợ tải và chạy model YOLOv5
import os                                       # Tương tác với hệ thống file (tạo thư mục)
import csv                                      # Ghi log lịch sử vào/ra dưới dạng CSV
import time                                     # Đo thời gian, tính FPS
import pandas as pd                             # Xuất dữ liệu ra file Excel
from datetime import datetime                   # Xử lý thời gian vào/ra
from PIL import Image, ImageTk                  # Chuyển ảnh OpenCV sang định dạng hiển thị trên Tkinter
import tkinter as tk                            # Xây dựng giao diện người dùng
from tkinter import Label, Button, Frame, ttk, messagebox, Entry, filedialog  # Các widget của Tkinter

# Các module tự viết riêng cho dự án
import function.utils_rotate as utils_rotate    # Hàm xoay và chỉnh sửa ảnh biển số
import function.helper as helper                # Hàm hỗ trợ đọc biển số từ model OCR

# Các hàm thao tác với database (SQLite)
from database.db import (
    init_db,                                    # Khởi tạo database
    save_record,                                # Lưu bản ghi vào/ra
    get_all_records,                            # Lấy toàn bộ lịch sử
    search_vehicle,                             # Tìm kiếm theo biển số
    check_vehicle_in_parking,                   # Kiểm tra xe đang trong bãi hay không
    get_parking_slots_status,                   # Lấy trạng thái các vị trí đỗ
    clear_all_data                              # Xóa toàn bộ dữ liệu (reset hệ thống)
)

# ===================================================================
# 1. CHUẨN BỊ THƯ MỤC VÀ FILE LOG
# ===================================================================
os.makedirs("logs", exist_ok=True)              # Tạo thư mục logs nếu chưa có
os.makedirs("result", exist_ok=True)            # Thư mục lưu kết quả (nếu cần mở rộng sau)
os.makedirs("images/in", exist_ok=True)         # Thư mục lưu ảnh xe vào
os.makedirs("images/out", exist_ok=True)        # Thư mục lưu ảnh xe ra

csv_path = "logs/license_log.csv"               # Đường dẫn file CSV lưu lịch sử
if not os.path.exists(csv_path):                 # Nếu file chưa tồn tại thì tạo mới
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ID", "Biển số", "Thời gian vào", "Thời gian ra", "Sự kiện", "Vị trí", "Ảnh"])

# In thông báo khởi động để dễ theo dõi trên console
print("=" * 60)
print("🚀 KHỞI ĐỘNG HỆ THỐNG QUẢN LÝ BÃI ĐỖ XE")
print("=" * 60)

# Khởi tạo database, nếu lỗi thì dừng chương trình ngay
if not init_db():
    print("❌ Không thể khởi động. Vui lòng kiểm tra kết nối database!")
    exit(1)

# ===================================================================
# 2. TẢI MÔ HÌNH NHẬN DIỆN BIỂN SỐ (YOLOv5)
# ===================================================================
print("🔹 Đang tải mô hình AI...")
try:
    # Model phát hiện vị trí biển số trong khung hình
    yolo_LP_detect = torch.hub.load(
        'yolov5', 'custom', path='model/LP_detector_nano_61.pt',
        force_reload=True, source='local'
    )
    # Model đọc chữ trên biển số (OCR)
    yolo_license_plate = torch.hub.load(
        'yolov5', 'custom', path='model/LP_ocr_nano_62.pt',
        force_reload=True, source='local'
    )
    yolo_license_plate.conf = 0.6               # Đặt ngưỡng confidence để giảm nhận nhầm
    print("✅ Mô hình AI đã sẵn sàng!")
except Exception as e:
    print(f"❌ Lỗi tải mô hình: {e}")
    exit(1)

print("=" * 60)

# ===================================================================
# 3. BIẾN TOÀN CỤC VÀ CẤU HÌNH NHẬN DIỆN
# ===================================================================
detection_buffer = {}       # Buffer lưu tạm các lần nhận diện của từng biển số (chống nhiễu)
processed_cache = {}        # Cache thời gian lần cuối lưu để thực hiện cooldown

# Cấu hình nhận diện đã được tối ưu qua thử nghiệm thực tế
DETECTION_WINDOW = 7.0      # Thời gian quan sát tối đa (7 giây)
MIN_DETECTIONS = 20         # Phải nhận diện liên tiếp ít nhất 20 frame mới ghi nhận
COOLDOWN_TIME = 20.0        # Sau khi lưu, chờ 20 giây mới cho phép lưu lại cùng biển số

# ===================================================================
# 4. CÁC HÀM HỖ TRỢ
# ===================================================================

def save_plate_image(crop_img, bien_so, is_entry):
    """Lưu ảnh biển số đã crop vào thư mục tương ứng (vào hoặc ra)"""
    try:
        folder = "images/in" if is_entry else "images/out"   # Chọn thư mục theo sự kiện
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S") # Tên file có thời gian
        clean_plate = bien_so.replace("-", "").replace(" ", "") # Loại bỏ ký tự không cần
        filename = f"{folder}/{clean_plate}_{timestamp}.jpg"
        cv2.imwrite(filename, crop_img)                     # Lưu ảnh bằng OpenCV
        print(f"📸 Đã lưu ảnh: {filename}")
        return filename
    except Exception as e:
        print(f"⚠️ Lỗi lưu ảnh: {e}")
        return ""

def save_to_csv(record):
    """Ghi một bản ghi mới vào file CSV log"""
    try:
        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                record.id, record.bien_so, record.time_in, 
                record.time_out, record.su_kien, record.vi_tri_do, record.anh_bienso
            ])
    except Exception as e:
        print(f"⚠️ Lỗi ghi CSV: {e}")

def export_csv():
    """Xuất toàn bộ dữ liệu từ database ra file CSV do người dùng chọn"""
    records = get_all_records()
    if not records:
        messagebox.showinfo("Thông báo", "Không có dữ liệu!")
        return
    filename = filedialog.asksaveasfilename(
        defaultextension=".csv",
        filetypes=[("CSV", "*.csv")],
        initialfile=f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )
    if filename:
        try:
            with open(filename, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["ID", "Biển số", "Vào", "Ra", "Sự kiện", "Vị trí", "Ảnh"])
                for r in records:
                    writer.writerow([r.id, r.bien_so, r.time_in, r.time_out, r.su_kien, r.vi_tri_do, r.anh_bienso])
            messagebox.showinfo("Thành công", f"✅ Đã xuất {len(records)} bản ghi vào CSV!")
        except Exception as e:
            messagebox.showerror("Lỗi", str(e))

def export_excel():
    """Xuất toàn bộ dữ liệu ra file Excel (.xlsx)"""
    records = get_all_records()
    if not records:
        messagebox.showinfo("Thông báo", "Không có dữ liệu!")
        return
    filename = filedialog.asksaveasfilename(
        defaultextension=".xlsx",
        filetypes=[("Excel", "*.xlsx")],
        initialfile=f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    )
    if filename:
        try:
            df = pd.DataFrame([
                (r.id, r.bien_so, r.time_in, r.time_out, r.su_kien, r.vi_tri_do, r.anh_bienso)
                for r in records
            ], columns=["ID", "Biển số", "Vào", "Ra", "Sự kiện", "Vị trí", "Ảnh"])
            df.to_excel(filename, index=False, engine='openpyxl')
            messagebox.showinfo("Thành công", f"✅ Đã xuất {len(records)} bản ghi vào Excel!")
        except Exception as e:
            messagebox.showerror("Lỗi", str(e))

def do_search():
    """Tìm kiếm xe theo biển số và hiển thị thông tin chi tiết nhất"""
    keyword = entry_search.get().strip()
    if not keyword:
        messagebox.showwarning("Cảnh báo", "Vui lòng nhập biển số!")
        return
    results = search_vehicle(keyword)
    refresh_table(results if results else [])
    if results:
        latest = results[0]
        lbl_plate.config(text=f"Biển số: {latest.bien_so}")
        lbl_slot.config(text=f"Vị trí: {latest.vi_tri_do or '---'}")
        if latest.time_in:
            lbl_time_in.config(text=f"Thời gian vào: {latest.time_in.strftime('%d/%m/%Y %H:%M:%S')}", fg="#16a34a")
        else:
            lbl_time_in.config(text="Thời gian vào: ---", fg="#6b7280")
        if latest.time_out:
            lbl_time_out.config(text=f"Thời gian ra: {latest.time_out.strftime('%d/%m/%Y %H:%M:%S')}", fg="#dc2626")
        else:
            lbl_time_out.config(text="Thời gian ra: Chưa ra", fg="#f59e0b")
        if latest.anh_bienso and os.path.exists(latest.anh_bienso):
            try:
                img = cv2.imread(latest.anh_bienso)
                rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(rgb).resize((150, 70))
                tk_img = ImageTk.PhotoImage(pil_img)
                lbl_plate_img.config(image=tk_img)
                lbl_plate_img.image = tk_img
            except:
                pass
        status = "Đang đỗ" if latest.time_out is None else "Đã ra"
        messagebox.showinfo("✅ Tìm thấy", 
                            f"Biển số: {latest.bien_so}\nTrạng thái: {status}\nVị trí: {latest.vi_tri_do or 'Không xác định'}\nTìm thấy {len(results)} bản ghi")
    else:
        # Reset giao diện khi không tìm thấy
        lbl_plate.config(text="Biển số: ---")
        lbl_time_in.config(text="Thời gian vào: ---", fg="#6b7280")
        lbl_time_out.config(text="Thời gian ra: ---", fg="#6b7280")
        lbl_slot.config(text="Vị trí: ---")
        lbl_plate_img.config(image="")
        messagebox.showinfo("❌ Không tìm thấy", f"Không có kết quả cho biển số '{keyword}'")

# ===================================================================
# 5. XÂY DỰNG GIAO DIỆN NGƯỜI DÙNG (TKINTER)
# ===================================================================
root = tk.Tk()
root.title("🚗 HỆ THỐNG QUẢN LÝ BÃI ĐỖ XE")
root.configure(bg="#f3f4f6")
root.resizable(False, False)
# Đặt cửa sổ vào giữa màn hình
screen_w = root.winfo_screenwidth()
screen_h = root.winfo_screenheight()
win_w, win_h = 1200, 750
x = (screen_w - win_w) // 2
y = (screen_h - win_h) // 2
root.geometry(f"{win_w}x{win_h}+{x}+{y}")
# Force cửa sổ lên foreground
root.deiconify()
root.lift()
root.attributes('-topmost', True)
root.after(500, lambda: root.attributes('-topmost', False))  # Tắt topmost sau 0.5s

# Cấu hình style cho Treeview (bảng lịch sử)
style = ttk.Style()
style.theme_use("clam")
style.configure("Treeview", background="white", foreground="black", rowheight=28, fieldbackground="white", font=("Segoe UI", 10))
style.configure("Treeview.Heading", font=("Segoe UI", 11, "bold"), background="#0d6efd", foreground="white")

# Header chính của ứng dụng
Frame(root, bg="#0d6efd", height=60).place(x=0, y=0, width=1200)
Label(root.winfo_children()[0], text="🚘 HỆ THỐNG QUẢN LÝ BÃI ĐỖ XE",
      font=("Segoe UI", 20, "bold"), fg="white", bg="#0d6efd").pack(expand=True)

# Khung hiển thị trạng thái các vị trí đỗ xe
frame_slots = Frame(root, bg="#f8fafc", highlightbackground="#cbd5e1", highlightthickness=1)
frame_slots.place(x=25, y=70, width=1145, height=140)
Label(frame_slots, text="🅿️ TRẠNG THÁI VỊ TRÍ ĐỖ XE", 
      font=("Segoe UI", 12, "bold"), bg="#f8fafc", fg="#0d6efd").pack(pady=5)
slots_container = Frame(frame_slots, bg="#f8fafc")
slots_container.pack(fill="both", expand=True, padx=10, pady=5)

def render_parking_slots():
    """Cập nhật lại giao diện các ô vị trí đỗ (xanh: trống, đỏ: có xe)"""
    for widget in slots_container.winfo_children():
        widget.destroy()
    slots = get_parking_slots_status()
    for idx, slot in enumerate(slots[:10]):  # Chỉ hiển thị 10 vị trí để giao diện gọn
        vi_tri = slot["vi_tri"]
        status = slot["status"]
        bien_so = slot["bien_so"]
        if status == "TRỐNG":
            bg_color = "#10b981"    # Xanh lá
            fg_color = "white"
            text = f"{vi_tri}\n✓ TRỐNG"
        else:
            bg_color = "#ef4444"    # Đỏ
            fg_color = "white"
            text = f"{vi_tri}\n🚗 {bien_so[:8] if bien_so else 'CÓ XE'}"
        slot_frame = Frame(slots_container, bg=bg_color, highlightbackground="#d1d5db", highlightthickness=2)
        slot_frame.grid(row=0, column=idx, padx=8, pady=5, sticky="nsew")
        Label(slot_frame, text=text, font=("Segoe UI", 9, "bold"),
              bg=bg_color, fg=fg_color, width=10, height=4).pack(fill="both", expand=True)
    for i in range(10):
        slots_container.grid_columnconfigure(i, weight=1)

render_parking_slots()  # Gọi lần đầu để hiển thị trạng thái ban đầu

# Khung hiển thị video từ camera
frame_video = Frame(root, bg="white", highlightbackground="#cbd5e1", highlightthickness=1)
frame_video.place(x=25, y=220, width=550, height=400)
lbl_camera = Label(frame_video, bg="white")
lbl_camera.pack(fill="both", expand=True)
lbl_fps = Label(frame_video, text="FPS: --", font=("Segoe UI", 10, "bold"), bg="white", fg="#16a34a")
lbl_fps.place(x=470, y=10)

# Khung thông tin xe hiện tại
frame_info = Frame(root, bg="white", highlightbackground="#cbd5e1", highlightthickness=1)
frame_info.place(x=600, y=220, width=570, height=200)
Label(frame_info, text="📋 THÔNG TIN XE", font=("Segoe UI", 13, "bold"),
      bg="white", fg="#0d6efd").place(x=220, y=10)
lbl_plate_img = Label(frame_info, bg="#f9fafb", relief="solid", bd=1)
lbl_plate_img.place(x=210, y=50, width=150, height=70)
lbl_plate = Label(frame_info, text="Biển số: ---", font=("Segoe UI", 11, "bold"), bg="white", fg="#111827")
lbl_plate.place(x=30, y=130)
lbl_slot = Label(frame_info, text="Vị trí: ---", font=("Segoe UI", 11, "bold"), bg="white", fg="#f59e0b")
lbl_slot.place(x=380, y=130)
lbl_time_in = Label(frame_info, text="Thời gian vào: ---", font=("Segoe UI", 10), bg="white", fg="#16a34a")
lbl_time_in.place(x=30, y=160)
lbl_time_out = Label(frame_info, text="Thời gian ra: Chưa ra", font=("Segoe UI", 10), bg="white", fg="#dc2626")
lbl_time_out.place(x=30, y=180)
lbl_counter = Label(frame_info, text="Số lần nhận diện: 0", font=("Segoe UI", 10, "bold"), bg="white", fg="#8b5cf6")
lbl_counter.place(x=380, y=160)

# Khung các nút điều khiển
frame_controls = Frame(root, bg="white", highlightbackground="#cbd5e1", highlightthickness=1)
frame_controls.place(x=600, y=440, width=570, height=180)
Label(frame_controls, text="🔍 TÌM KIẾM BIỂN SỐ", font=("Segoe UI", 12, "bold"),
      bg="white", fg="#8b5cf6").place(x=20, y=15)
entry_search = Entry(frame_controls, font=("Segoe UI", 12), relief="solid", bd=1)
entry_search.place(x=20, y=50, width=280, height=35)
entry_search.bind("<Return>", lambda e: do_search())  # Nhấn Enter cũng tìm được
Button(frame_controls, text="🔍 Tìm", font=("Segoe UI", 10, "bold"),
       bg="#8b5cf6", fg="white", relief="flat", cursor="hand2",
       command=do_search).place(x=310, y=50, width=80, height=35)

def upload_image():
    """Cho phép người dùng upload ảnh tĩnh để test nhận diện thủ công"""
    file_path = filedialog.askopenfilename(filetypes=[("Image files", "*.jpg *.jpeg *.png")])
    if not file_path:
        return
    img = cv2.imread(file_path)
    if img is None:
        messagebox.showwarning("Cảnh báo", "Ảnh không hợp lệ!")
        return
    # Hiển thị ảnh lên khung video
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(rgb).resize((550, 400))
    imgtk = ImageTk.PhotoImage(pil_img)
    lbl_camera.config(image=imgtk)
    lbl_camera.image = imgtk

    # Thực hiện nhận diện giống như camera realtime
    try:
        results = yolo_LP_detect(img, size=640)
    except Exception as e:
        messagebox.showwarning("Lỗi", f"Không chạy được model: {e}")
        return

    detected_plate = None
    crop_img = None

    for det in results.pandas().xyxy[0].values.tolist():
        x1, y1, x2, y2 = map(int, det[:4])
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(img.shape[1]-1, x2), min(img.shape[0]-1, y2)
        if x2 <= x1 or y2 <= y1:
            continue
        crop_img = img[y1:y2, x1:x2]
        if crop_img is None or crop_img.size == 0:
            continue

        lp_text = "unknown"
        for cc in range(2):
            for ct in range(2):
                try:
                    lp_text = helper.read_plate(yolo_license_plate, utils_rotate.deskew(crop_img, cc, ct))
                except:
                    pass
                if lp_text != "unknown":
                    break
            if lp_text != "unknown":
                break

        if lp_text != "unknown":
            detected_plate = lp_text
            break

    if not detected_plate:
        messagebox.showinfo("THÔNG BÁO", "Không nhận diện được biển số trong ảnh này!")
        return

    # Cập nhật giao diện và lưu dữ liệu
    lbl_plate.config(text=f"Biển số: {detected_plate}")
    lbl_time_in.config(text=f"Thời gian vào: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", fg="#16a34a")
    lbl_time_out.config(text="Thời gian ra: Chưa ra", fg="#f59e0b")
    try:
        is_in, info = check_vehicle_in_parking(detected_plate)
        is_entry = not is_in
        img_path = save_plate_image(crop_img, detected_plate, is_entry)
        success, msg, record = save_record(detected_plate, img_path)
        if success and record:
            lbl_slot.config(text=f"Vị trí: {record.vi_tri_do or '---'}")
            save_to_csv(record)
            refresh_table()
            render_parking_slots()
            try:
                rgb2 = cv2.cvtColor(crop_img, cv2.COLOR_BGR2RGB)
                pil_img2 = Image.fromarray(rgb2).resize((150, 70))
                tk_img2 = ImageTk.PhotoImage(pil_img2)
                lbl_plate_img.config(image=tk_img2)
                lbl_plate_img.image = tk_img2
            except:
                pass
            messagebox.showinfo("✅ Thành công", msg)
        else:
            messagebox.showwarning("⚠️", msg)
    except Exception as e:
        messagebox.showerror("Lỗi", str(e))

Button(frame_controls, text="📷 Up Ảnh", font=("Segoe UI", 10, "bold"),
       bg="#6366f1", fg="white", relief="flat", cursor="hand2",
       command=upload_image).place(x=400, y=50, width=100, height=35)

Label(frame_controls, text="📤 XUẤT DỮ LIỆU", font=("Segoe UI", 12, "bold"),
      bg="white", fg="#10b981").place(x=20, y=105)
Button(frame_controls, text="📄 Xuất CSV", font=("Segoe UI", 10, "bold"),
       bg="#3b82f6", fg="white", relief="flat", cursor="hand2",
       command=export_csv).place(x=20, y=135, width=130, height=35)
Button(frame_controls, text="📊 Xuất Excel", font=("Segoe UI", 10, "bold"),
       bg="#10b981", fg="white", relief="flat", cursor="hand2",
       command=export_excel).place(x=165, y=135, width=130, height=35)

def reset_detection_buffer():
    """Xóa toàn bộ dữ liệu hệ thống (database, buffer, giao diện)"""
    confirm = messagebox.askyesno("⚠️ Xác nhận xóa dữ liệu", 
        "Bạn có chắc muốn xóa TẤT CẢ dữ liệu?\n\n• Xóa toàn bộ lịch sử xe vào/ra\n• Reset trạng thái vị trí đỗ xe\n• Xóa bộ nhớ nhận diện\n\n⚠️ Hành động này KHÔNG THỂ KHÔI PHỤC!")
    if not confirm:
        return
    try:
        success, message = clear_all_data()
        if success:
            detection_buffer.clear()
            processed_cache.clear()
            lbl_plate.config(text="Biển số: ---")
            lbl_time_in.config(text="Thời gian vào: ---", fg="#6b7280")
            lbl_time_out.config(text="Thời gian ra: ---", fg="#6b7280")
            lbl_slot.config(text="Vị trí: ---")
            lbl_plate_img.config(image="")
            lbl_counter.config(text="Số lần nhận diện: 0")
            refresh_table()
            render_parking_slots()
            print("🔄 " + message)
            messagebox.showinfo("✅ Thành công", "Đã xóa toàn bộ dữ liệu và reset hệ thống!")
        else:
            messagebox.showerror("❌ Lỗi", message)
    except Exception as e:
        messagebox.showerror("❌ Lỗi", f"Không thể xóa dữ liệu:\n{str(e)}")

Button(frame_controls, text="🔄 Tải lại", font=("Segoe UI", 10, "bold"),
       bg="#f59e0b", fg="white", relief="flat", cursor="hand2",
       command=reset_detection_buffer).place(x=310, y=135, width=130, height=35)

Button(frame_controls, text="🚪 Thoát", font=("Segoe UI", 10, "bold"),
       bg="#EF4444", fg="white", relief="flat", cursor="hand2",
       command=root.quit).place(x=455, y=135, width=90, height=35)

# Bảng hiển thị lịch sử vào/ra
frame_table = Frame(root, bg="white", highlightbackground="#cbd5e1", highlightthickness=1)
frame_table.place(x=25, y=640, width=1145, height=100)
columns = ("ID", "Biển số", "Vị trí", "Thời gian vào", "Thời gian ra", "Sự kiện")
tree = ttk.Treeview(frame_table, columns=columns, show="headings")
for col in columns:
    tree.heading(col, text=col)
    width = {"ID": 50, "Biển số": 120, "Vị trí": 80, "Thời gian vào": 160, "Thời gian ra": 160, "Sự kiện": 100}
    tree.column(col, anchor="center", width=width.get(col, 100))
tree.pack(fill="both", expand=True, padx=5, pady=5)

def refresh_table(records=None):
    """Làm mới nội dung bảng lịch sử"""
    for i in tree.get_children():
        tree.delete(i)
    rows = records if records else get_all_records()
    for r in rows:
        try:
            tree.insert("", "end", values=(
                r.id, r.bien_so, r.vi_tri_do or "---",
                r.time_in.strftime("%d/%m/%Y %H:%M:%S") if r.time_in else "",
                r.time_out.strftime("%d/%m/%Y %H:%M:%S") if r.time_out else "",
                r.su_kien
            ))
        except:
            pass

# ===================================================================
# 6. XỬ LÝ VIDEO REALTIME TỪ CAMERA
# ===================================================================
cap = cv2.VideoCapture(0)           # Mở camera mặc định (0 = webcam)
prev_time = time.time()             # Biến để tính FPS

def update_frame():
    """Vòng lặp chính: đọc frame, nhận diện, cập nhật giao diện"""
    global prev_time, detection_buffer, processed_cache
    ret, frame = cap.read()
    if not ret:
        root.after(30, update_frame)
        return

    current_time = time.time()

    # Phát hiện biển số trong frame hiện tại
    try:
        results = yolo_LP_detect(frame, size=640)
    except:
        root.after(1000, update_frame)
        return

    detected_plate = None
    crop_img = None

    for det in results.pandas().xyxy[0].values.tolist():
        x1, y1, x2, y2 = map(int, det[:4])
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(frame.shape[1]-1, x2), min(frame.shape[0]-1, y2)
        if x2 <= x1 or y2 <= y1:
            continue
        crop_img = frame[y1:y2, x1:x2]
        if crop_img is None or crop_img.size == 0:
            continue

        lp_text = "unknown"
        for cc in range(2):
            for ct in range(2):
                try:
                    lp_text = helper.read_plate(yolo_license_plate, utils_rotate.deskew(crop_img, cc, ct))
                except:
                    pass
                if lp_text != "unknown":
                    break
            if lp_text != "unknown":
                break

        if lp_text != "unknown":
            detected_plate = lp_text
            cv2.rectangle(frame, (x1, y1), (x2, y2), (13, 110, 253), 2)
            cv2.putText(frame, lp_text, (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (13, 110, 253), 2)
            break

    # Logic chống nhận diện nhầm (buffer + cooldown)
    if detected_plate:
        last_saved = processed_cache.get(detected_plate, 0)
        if current_time - last_saved < COOLDOWN_TIME:
            remaining = int(COOLDOWN_TIME - (current_time - last_saved))
            lbl_counter.config(text=f"⏳ Chờ: {remaining}s")
        else:
            if detected_plate not in detection_buffer:
                detection_buffer[detected_plate] = {
                    'readings': [],
                    'first_time': current_time,
                    'crop': crop_img
                }
            buf = detection_buffer[detected_plate]

            if current_time - buf['first_time'] <= DETECTION_WINDOW:
                buf['readings'].append(current_time)
                buf['crop'] = crop_img
                count = len(buf['readings'])
                lbl_counter.config(text=f"Nhận diện: {count}/{MIN_DETECTIONS}")

                if count >= MIN_DETECTIONS:
                    now = datetime.now()
                    lbl_plate.config(text=f"Biển số: {detected_plate}")
                    lbl_time_in.config(text=f"Thời gian vào: {now.strftime('%d/%m/%Y %H:%M:%S')}", fg="#16a34a")
                    lbl_time_out.config(text="Thời gian ra: Chưa ra", fg="#f59e0b")
                    try:
                        is_in, info = check_vehicle_in_parking(detected_plate)
                        is_entry = not is_in
                        img_path = save_plate_image(buf['crop'], detected_plate, is_entry)
                        success, msg, record = save_record(detected_plate, img_path)
                        if success and record:
                            lbl_slot.config(text=f"Vị trí: {record.vi_tri_do or '---'}")
                            save_to_csv(record)
                            refresh_table()
                            render_parking_slots()
                            try:
                                rgb = cv2.cvtColor(buf['crop'], cv2.COLOR_BGR2RGB)
                                pil_img = Image.fromarray(rgb).resize((150, 70))
                                tk_img = ImageTk.PhotoImage(pil_img)
                                lbl_plate_img.config(image=tk_img)
                                lbl_plate_img.image = tk_img
                            except:
                                pass
                            root.after(100, lambda m=msg: messagebox.showinfo("✅ Thành công", m))
                        else:
                            root.after(100, lambda m=msg: messagebox.showwarning("⚠️ Cảnh báo", m))
                        processed_cache[detected_plate] = current_time
                    except Exception as e:
                        print(f"❌ Lỗi: {e}")
                    del detection_buffer[detected_plate]
            else:
                del detection_buffer[detected_plate]
    else:
        lbl_counter.config(text="Số lần nhận diện: 0")

    # Dọn buffer cũ quá hạn
    for plate in list(detection_buffer.keys()):
        if current_time - detection_buffer[plate]['first_time'] > DETECTION_WINDOW:
            del detection_buffer[plate]

    # Tính và hiển thị FPS
    fps = 1 / (current_time - prev_time) if (current_time - prev_time) > 0 else 0
    prev_time = current_time
    lbl_fps.config(text=f"FPS: {fps:.1f}")

    # Hiển thị frame lên giao diện Tkinter
    try:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb).resize((550, 400))
        imgtk = ImageTk.PhotoImage(pil)
        lbl_camera.config(image=imgtk)
        lbl_camera.image = imgtk
    except:
        pass

    root.after(30, update_frame)  # Lặp lại sau 30ms

# ===================================================================
# 7. KẾT THÚC CHƯƠNG TRÌNH
# ===================================================================
def on_close():
    """Xử lý khi đóng cửa sổ"""
    print("\n🛑 Đóng hệ thống...")
    cap.release()                       # Giải phóng camera
    cv2.destroyAllWindows()             # Đóng các cửa sổ OpenCV (nếu có)
    root.destroy()

root.protocol("WM_DELETE_WINDOW", on_close)

# Khởi chạy giao diện
refresh_table()
render_parking_slots()
update_frame()
root.mainloop()