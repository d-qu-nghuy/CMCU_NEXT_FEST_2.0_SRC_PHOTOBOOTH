import time
import os
import shutil
import requests
import subprocess
import threading
import queue
import winsound
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ==========================================
# THIẾT LẬP ĐƯỜNG DẪN & API 
# ==========================================
API_URL = "https://script.google.com/macros/s/AKfycbz_m-F4cTM-vvyyaUs9Yf0QNoPxpuAFZtNbUQyYEy-GsxfgngyJHb3Lf-m-OlggkC1b/exec"
DROP_FOLDER = r"E:\Club's Day Photobooth 2026 - 2027\1_Tether_Drop"
FINAL_FOLDER = r"E:\Club's Day Photobooth 2026 - 2027\2_Final_Export"
DROPLET_PATH = r"E:\Club's Day Photobooth 2026 - 2027\Test Action (2).exe"

# ==========================================
# BỘ NHỚ ĐỆM, HÀNG ĐỢI & BỘ ĐẾM SỐ LƯỢNG ẢNH
# ==========================================
current_mssv = "Khach_Chua_Dang_Ky"
photo_queue = queue.Queue()
photo_counts = {}  # Từ điển lưu số lượng ảnh đã chụp của mỗi sinh viên

def sync_admin_status():
    """LUỒNG 1: Liên tục hỏi Google Sheets (3s/lần) để tránh bị khóa API"""
    global current_mssv
    while True:
        try:
            response = requests.get(API_URL + "?action=sync_student", timeout=5).json()
            
            if response.get('status') == 'success' and response.get('active'):
                new_mssv = str(response['active']['mssv'])
                new_name = str(response['active'].get('name', 'Khách VIP'))
                
                if new_name == 'Khách VIP' or new_name == new_mssv:
                    display_text = new_mssv
                else:
                    display_text = f"{new_name} {new_mssv}"
                
                if new_mssv != current_mssv:
                    current_mssv = new_mssv
                    
                    print("\n=====================================================================")
                    print(f" 🟢 ĐÃ CHỐT ĐƠN CHO: {display_text} - CÓ THỂ CHỤP NGAY!")
                    print("=====================================================================\n")
                    winsound.Beep(1500, 500) 
                    
            elif response.get('status') == 'success' and not response.get('active'):
                current_mssv = "Khach_Chua_Dang_Ky"
        except Exception as e:
            pass 
        
        time.sleep(3)

def wait_for_file_ready(file_path, timeout=20):
    """Kiểm tra xem Cáp USB hoặc Photoshop đã nhả file ra chưa"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            os.rename(file_path, file_path)
            return True
        except OSError:
            time.sleep(0.2)
    return False

class PhotoboothHandler(FileSystemEventHandler):
    """LUỒNG 2: Giám sát ổ cứng. Vừa có ảnh là GẮN TAG ngay lập tức"""
    def on_created(self, event):
        if event.is_directory or not event.src_path.lower().endswith(('.jpg', '.jpeg')):
            return
            
        file_path = event.src_path
        snapped_mssv = current_mssv
        
        # --- BỘ ĐẾM SỐ THỨ TỰ ẢNH ---
        global photo_counts
        photo_counts[snapped_mssv] = photo_counts.get(snapped_mssv, 0) + 1
        current_count = photo_counts[snapped_mssv]
        
        print(f"[+] Bắt được ảnh (Tấm #{current_count}): {os.path.basename(file_path)} ---> Đã gắn tag: {snapped_mssv}")
        
        # Đóng gói cả mssv LẪN current_count vào hàng đợi cho Photoshop
        photo_queue.put((file_path, snapped_mssv, current_count))

def photo_processor_worker():
    """LUỒNG 3: Nhặt ảnh từ hàng đợi ra cho Photoshop xử lý"""
    while True:
        # Nhận cả 3 thông tin từ hàng đợi: đường dẫn, MSSV và Số thứ tự
        file_path, mssv, current_count = photo_queue.get()
        
        if not wait_for_file_ready(file_path, timeout=5):
            print(f"[-] Lỗi: Cáp USB giữ file (Tấm #{current_count}) {os.path.basename(file_path)} quá lâu.")
            photo_queue.task_done()
            continue

        target_dir = os.path.join(FINAL_FOLDER, mssv)
        os.makedirs(target_dir, exist_ok=True)

        # Cập nhật hiển thị STT cho tiến trình Photoshop
        print(f"[*] Đang chạy Photoshop cho ảnh (Tấm #{current_count}): {os.path.basename(file_path)}...")
        
        try:
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 7 
                subprocess.run([DROPLET_PATH, file_path], startupinfo=startupinfo, creationflags=0x08000000, timeout=30)
            else:
                subprocess.run([DROPLET_PATH, file_path], timeout=30)
            
            if wait_for_file_ready(file_path, timeout=5):
                file_name = os.path.basename(file_path)
                final_file_path = os.path.join(target_dir, file_name)
                try:
                    shutil.move(file_path, final_file_path)
                    # Cập nhật hiển thị STT cho trạng thái SUCCESS
                    print(f"[SUCCESS] Cất ảnh (Tấm #{current_count}) {file_name} thành công vào thư mục {mssv}!\n")
                except Exception as e:
                    print(f"[LỖI LƯU TRỮ] {e}\n")
            else:
                print(f"[-] LỖI: Photoshop vẫn đang khóa file (Tấm #{current_count}) {os.path.basename(file_path)}\n")

        except subprocess.TimeoutExpired:
            print(f"[-] LỖI TIMEOUT: Photoshop bị treo khi xử lý (Tấm #{current_count}) {os.path.basename(file_path)}. Bỏ qua file!\n")
        except Exception as e:
            print(f"[-] Không thể gọi Droplet cho (Tấm #{current_count}): {e}\n")
        
        photo_queue.task_done()

# ==========================================
# KHỞI ĐỘNG HỆ THỐNG
# ==========================================
if __name__ == "__main__":
    os.makedirs(DROP_FOLDER, exist_ok=True)
    os.makedirs(FINAL_FOLDER, exist_ok=True)
    
    threading.Thread(target=sync_admin_status, daemon=True).start()
    threading.Thread(target=photo_processor_worker, daemon=True).start()
    
    event_handler = PhotoboothHandler()
    observer = Observer()
    observer.schedule(event_handler, DROP_FOLDER, recursive=False)
    observer.start()
    
    print("=====================================================================")
    print(" HỆ THỐNG PHOTOBOOTH ĐA LUỒNG ĐANG CHẠY...")
    print(f" Theo dõi: {DROP_FOLDER}")
    print(" BẬT LOA MÁY TÍNH ĐỂ NGHE TÍN HIỆU BÁO CHUYỂN NGƯỜI")
    print("=====================================================================\n")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("\n[!] Đã tắt hệ thống.")
    observer.join()