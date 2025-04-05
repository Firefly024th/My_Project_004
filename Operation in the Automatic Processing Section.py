import numpy as np
import tensorflow.lite as tflite
import paho.mqtt.client as mqtt
import time
import threading
import queue
import cv2

# โหลดโมเดล
interpreter = tflite.Interpreter(model_path="waste_classifier.tflite")
interpreter.allocate_tensors()

# ดึงข้อมูลอินพุตและเอาต์พุต
input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()

# ตั้งค่าขนาดอินพุตของโมเดล
input_shape = input_details[0]['shape']  # [1, 224, 224, 3]
input_size = (input_shape[1], input_shape[2])  # (224, 224)

# เปิดกล้อง
cap = cv2.VideoCapture(1)  # ใช้ 0 แทน 1 ถ้ากล้องหลักเชื่อมต่อที่ 0

# ตั้งค่าตัวแปร MQTT
broker = "192.168.43.185"
port = 1883
topic = "Waste"

client = mqtt.Client(protocol=mqtt.MQTTv5)
client.connect(broker, port, 60)
client.loop_start()

# กำหนดคลาสขยะ
class_labels = ["Can", "Plastic_Bottle", "General_Waste", "Glass"]

# ใช้ Queue และ Event สำหรับควบคุมการทำงาน
frame_queue = queue.Queue(maxsize=1)  # จำกัดขนาด queue
message_queue = queue.Queue()
process_event = threading.Event()  # ควบคุมการประมวลผล

running = True  # ใช้หยุดเธรด
last_message = None
last_sent_time = 0  # เวลาที่ส่ง MQTT ล่าสุด
send_interval = 8  # ส่งซ้ำทุก 8 วินาที (ปรับค่าได้)
last_print_time = 0  # เวลาล่าสุดที่พิมพ์ข้อความ

# ===================== 📷 เธรดสำหรับอ่านกล้อง =====================
def read_camera():
    global running
    while running:
        ret, frame = cap.read()
        if ret:
            if not frame_queue.full():  # ถ้า Queue ไม่เต็ม ให้เพิ่มภาพใหม่
                frame_queue.put(frame)
            cv2.imshow("Camera", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            running = False  # ออกจากลูปเมื่อกด q

# ===================== 📷 เธรดสำหรับอ่านกล้อง =====================

def draw_crosshairs(frame):
    """ วาดกากบาทลงบนภาพ """
    height, width = frame.shape[:2]
    center_x, center_y = width // 2, height // 2

    # วาดกากบาท
    cv2.line(frame, (center_x - 20, center_y), (center_x + 20, center_y), (0, 255, 0), 2)
    cv2.line(frame, (center_x, center_y - 20), (center_x, center_y + 20), (0, 255, 0), 2)
    
    return center_x, center_y

def detect_object_in_crosshair(frame, center_x, center_y, threshold=100):
    """ ตรวจจับวัตถุที่อยู่ในพื้นที่ของกากบาท """
    # แปลงเป็นภาพขาวดำ
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
    
    # หาขอบเขตของวัตถุในภาพ
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    for contour in contours:
        # หา bounding box ของวัตถุ
        x, y, w, h = cv2.boundingRect(contour)
        # ตรวจสอบว่ากากบาทตัดผ่านวัตถุ
        if x < center_x < x + w and y < center_y < y + h:
            return True
    return False

# ===================== 🔍 เธรดสำหรับประมวลผลภาพ =====================

def process_frame():
    global last_message, last_sent_time, last_print_time
    while running:
        try:
            frame = frame_queue.get(timeout=1)  # ดึงเฟรมจาก Queue
            center_x, center_y = draw_crosshairs(frame)  # วาดกากบาท
            object_detected = detect_object_in_crosshair(frame, center_x, center_y)

            # แปลงภาพให้ตรงกับขนาดอินพุตของโมเดล
            img = cv2.resize(frame, input_size)
            img = img.astype(np.float32) / 255.0  # Normalize
            img = np.expand_dims(img, axis=0)  # เพิ่มมิติเป็น [1, 224, 224, 3]

            # ใส่ภาพเข้าโมเดล
            interpreter.set_tensor(input_details[0]['index'], img)
            interpreter.invoke()

            # ดึงผลลัพธ์
            output_data = interpreter.get_tensor(output_details[0]['index'])[0]  # [4]
            predicted_class = np.argmax(output_data)
            confidence = np.max(output_data)

            # เรียงลำดับค่าความมั่นใจจากมากไปน้อย
            sorted_indices = np.argsort(output_data)[::-1]  # ค่าที่มั่นใจมากสุดจะอยู่ต้น
            best_index = sorted_indices[0]  # ค่าที่มั่นใจที่สุด
            second_best_index = sorted_indices[1]  # ค่าที่มั่นใจรองลงมา

            best_confidence = output_data[best_index]
            second_best_confidence = output_data[second_best_index]

            # ถ้าค่าที่มั่นใจที่สุดต่ำกว่า 0.85 ไม่ต้องส่งค่า
            if best_confidence < 0.88:
                current_time = time.time()
                if current_time - last_print_time > 2:
                    print("None - ความมั่นใจต่ำเกินไป")
                    last_print_time = current_time
                continue  # ไม่ส่งค่าและไม่ประมวลผลต่อ

            # ถ้าค่าที่มั่นใจที่สุดกับอันดับสองต่างกันน้อยเกินไป ไม่ต้องส่งค่า
            if best_confidence - second_best_confidence < 0.1:
                current_time = time.time()
                if current_time - last_print_time > 2:
                    print("None - ค่ามั่นใจใกล้กันเกินไป")
                    last_print_time = current_time
                continue

            # ส่งค่าเดียวที่มั่นใจที่สุด
            new_message = class_labels[best_index]
            current_time = time.time()

            if new_message != last_message or (current_time - last_sent_time > send_interval):
                last_message = new_message
                last_sent_time = current_time
                message_queue.put(new_message)

                # แสดงผลลัพธ์ที่คาดการณ์
                label = f"{class_labels[best_index]} ({best_confidence*100:.2f}%)"
                cv2.putText(frame, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

                print(f"✅ ตรวจพบ: {label}")

        except queue.Empty:
            continue

# ===================== 📡 เธรดสำหรับส่งข้อมูล MQTT =====================

def publish_mqtt():
    while running:
        try:
            msg = message_queue.get(timeout=1)
            client.publish(topic, msg)
            print(f"📢 Published: {msg}")
        except queue.Empty:
            continue

# ===================== 🚀 เริ่มรันเธรด =====================

camera_thread = threading.Thread(target=read_camera, daemon=True)
process_thread = threading.Thread(target=process_frame, daemon=True)
mqtt_thread = threading.Thread(target=publish_mqtt, daemon=True)

camera_thread.start()
process_thread.start()
mqtt_thread.start()

# ===================== 🎮 จับการกดปุ่มในเธรดหลัก =====================

while running:
    key = cv2.waitKey(1) & 0xFF
    if key == ord('q'):
        running = False  # หยุดเธรดทั้งหมด
        break
    time.sleep(0.1)  # ลด CPU Usage

# ===================== 🔚 ปิดการเชื่อมต่อ =====================

camera_thread.join()
process_thread.join()
mqtt_thread.join()

client.loop_stop()
client.disconnect()
cap.release()
cv2.destroyAllWindows()
