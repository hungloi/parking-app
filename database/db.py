import pyodbc
import csv
from datetime import datetime
import os

# CẤU HÌNH KẾT NỐI
SERVER = 'LOI\\SQLEXPRESS'
DATABASE = 'SmartParkingDB'
USERNAME = 'sa'
PASSWORD = '123'

CONNECTION_STRING = (
    f"DRIVER={{SQL Server}};"
    f"SERVER={SERVER};"
    f"DATABASE={DATABASE};"
    f"UID={USERNAME};"
    f"PWD={PASSWORD}"
)

def get_connection():
    """Tạo kết nối đến SQL Server"""
    try:
        conn = pyodbc.connect(CONNECTION_STRING)
        return conn
    except Exception as e:
        print(f"❌ Lỗi kết nối database: {e}")
        return None

def init_db():
    """Khởi tạo database và bảng"""
    conn = get_connection()
    if not conn:
        print("❌ Không thể khởi tạo database!")
        return False
    try:
        cursor = conn.cursor()
        cursor.execute("""
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='ParkingLogs' AND xtype='U')
            CREATE TABLE ParkingLogs (
                id INT IDENTITY(1,1) PRIMARY KEY,
                bien_so NVARCHAR(50) NOT NULL,
                time_in DATETIME NULL,
                time_out DATETIME NULL,
                su_kien NVARCHAR(50),
                anh_bienso NVARCHAR(255),
                vi_tri_do NVARCHAR(20) NULL
            )
        """)
        conn.commit()
        print("✅ Database đã sẵn sàng!")
        return True
    except Exception as e:
        print(f"❌ Lỗi khởi tạo: {e}")
        return False
    finally:
        conn.close()

def check_vehicle_in_parking(bien_so):
    """Kiểm tra xe có đang đỗ trong bãi không"""
    conn = get_connection()
    if not conn:
        return False, None
    try:
        cursor = conn.cursor()
        cursor.execute("EXEC sp_CheckVehicleInParking ?", (bien_so,))
        row = cursor.fetchone()
        if row:
            return True, {
                'id': row.id,
                'bien_so': row.bien_so,
                'time_in': row.time_in,
                'vi_tri_do': row.vi_tri_do,
                'anh_bienso': row.anh_bienso,
                'phut_da_do': row.phut_da_do
            }
        return False, None
    except Exception as e:
        print(f"❌ Lỗi kiểm tra xe: {e}")
        return False, None
    finally:
        conn.close()

def get_available_slots():
    """Lấy danh sách vị trí trống"""
    conn = get_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM fn_GetAvailableSlots()")
        slots = [row.vi_tri for row in cursor.fetchall()]
        return slots
    except Exception as e:
        print(f"❌ Lỗi lấy vị trí: {e}")
        return []
    finally:
        conn.close()

def save_vehicle_entry(bien_so, image_path, vi_tri_do=None):
    """Lưu thông tin xe vào bãi"""
    conn = get_connection()
    if not conn:
        return False, "Không thể kết nối database", None
    try:
        if not vi_tri_do:
            slots = get_available_slots()
            vi_tri_do = slots[0] if slots else "FULL"
        cursor = conn.cursor()
        cursor.execute("EXEC sp_VehicleEntry ?, ?, ?", (bien_so, image_path, vi_tri_do))
        row = cursor.fetchone()
        conn.commit()
        if row and getattr(row, 'success', 0) == 1:
            return True, row.message, row
        else:
            return False, getattr(row, 'message', 'Lỗi không xác định'), None
    except Exception as e:
        return False, f"Lỗi: {e}", None
    finally:
        conn.close()

def save_vehicle_exit(bien_so, image_path):
    """Lưu thông tin xe ra khỏi bãi"""
    conn = get_connection()
    if not conn:
        return False, "Không thể kết nối database", None
    try:
        cursor = conn.cursor()
        cursor.execute("EXEC sp_VehicleExit ?, ?", (bien_so, image_path))
        row = cursor.fetchone()
        conn.commit()
        if row and getattr(row, 'success', 0) == 1:
            msg = f"{row.message}\nThời gian đỗ: {getattr(row, 'phut_do', '')} phút"
            return True, msg, row
        else:
            return False, getattr(row, 'message', 'Lỗi không xác định'), None
    except Exception as e:
        return False, f"Lỗi: {e}", None
    finally:
        conn.close()

def save_record(bien_so, image_path):
    """Hàm thông minh: tự động xác định xe vào hay ra"""
    is_in_parking, _ = check_vehicle_in_parking(bien_so)
    if is_in_parking:
        return save_vehicle_exit(bien_so, image_path)
    else:
        return save_vehicle_entry(bien_so, image_path)

def get_all_records():
    """Lấy tất cả bản ghi"""
    conn = get_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM ParkingLogs ORDER BY id DESC")
        return cursor.fetchall()
    except Exception as e:
        print(f"❌ Lỗi đọc dữ liệu: {e}")
        return []
    finally:
        conn.close()

def search_vehicle(bien_so):
    """Tìm kiếm xe theo biển số"""
    conn = get_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("EXEC sp_SearchVehicle ?", (bien_so,))
        return cursor.fetchall()
    except Exception as e:
        print(f"❌ Lỗi tìm kiếm: {e}")
        return []
    finally:
        conn.close()

def export_to_csv(file_path=None):
    """Xuất dữ liệu ra CSV"""
    records = get_all_records()
    if not records:
        print("⚠️ Không có dữ liệu để xuất")
        return False
    os.makedirs("result", exist_ok=True)
    if not file_path:
        file_path = f"result/export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    try:
        with open(file_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["ID", "Biển số", "Thời gian vào", "Thời gian ra", "Sự kiện", "Vị trí", "Ảnh"])
            for r in records:
                writer.writerow([r.id, r.bien_so, r.time_in, r.time_out, r.su_kien, r.vi_tri_do, r.anh_bienso])
        print(f"✅ Đã xuất: {file_path}")
        return True
    except Exception as e:
        print(f"❌ Lỗi xuất CSV: {e}")
        return False

def get_parking_slots_status():
    """Lấy trạng thái tất cả 40 vị trí đỗ xe (A01-D10)"""
    conn = get_connection()
    if not conn:
        return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT vi_tri_do, bien_so FROM ParkingLogs 
            WHERE time_out IS NULL AND vi_tri_do IS NOT NULL
        """)
        busy_slots = {row.vi_tri_do: row.bien_so for row in cursor.fetchall()}
        all_slots = []
        for prefix in "ABCD":
            for num in range(1, 11):
                all_slots.append(f"{prefix}{num:02}")
        result = []
        for slot in all_slots:
            if slot in busy_slots:
                result.append({"vi_tri": slot, "status": "CÓ XE", "bien_so": busy_slots[slot]})
            else:
                result.append({"vi_tri": slot, "status": "TRỐNG", "bien_so": None})
        return result
    except Exception as e:
        print(f"❌ Lỗi lấy trạng thái vị trí: {e}")
        return []
    finally:
        conn.close()

def clear_all_data():
    """
    Xóa toàn bộ dữ liệu trong bảng ParkingLogs
    Returns:
        tuple: (success: bool, message: str)
    """
    conn = get_connection()
    if not conn:
        return False, "Không thể kết nối database!"
    
    try:
        cursor = conn.cursor()
        
        # Đếm số bản ghi trước khi xóa
        cursor.execute("SELECT COUNT(*) FROM ParkingLogs")
        count = cursor.fetchone()[0]
        
        # Xóa tất cả dữ liệu trong bảng ParkingLogs
        cursor.execute("DELETE FROM ParkingLogs")
        
        # Reset IDENTITY về 1
        cursor.execute("DBCC CHECKIDENT ('ParkingLogs', RESEED, 0)")
        
        conn.commit()
        
        message = f"✅ Đã xóa thành công {count} bản ghi!\n\n" \
                  f"• Tất cả dữ liệu xe vào/ra đã bị xóa\n" \
                  f"• Tất cả vị trí đỗ xe đã được giải phóng\n" \
                  f"• ID đã được reset về 1"
        
        print(f"🔄 {message}")
        return True, message
        
    except Exception as e:
        error_msg = f"Lỗi khi xóa dữ liệu: {str(e)}"
        print(f"❌ {error_msg}")
        return False, error_msg
        
    finally:
        conn.close()