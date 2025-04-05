import cv2
import numpy as np
import tensorflow.lite as tflite
import paho.mqtt.client as mqtt
import time

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
cap = cv2.VideoCapture(1)

# ตั้งค่าการเชื่อมต่อ MQTT
broker = "192.168.43.185"  # แก้ไขให้ตรงกับ MQTT Broker ของคุณ
port = 1883
topic = "Waste"

client = mqtt.Client(protocol=mqtt.MQTTv5)
client.connect(broker, port, 60)
client.loop_start()

# กำหนดคลาสขยะ
class_labels = ["Can", "Plastic_Bottle", "General_Waste", "Glass"]

while True:
    ret, frame = cap.read()
    if not ret:
        print("❌ ไม่สามารถอ่านภาพจากกล้องได้")
        continue  # ข้ามไปอ่านภาพใหม่

    # แสดงภาพจากกล้อง
    cv2.imshow("Camera", frame)

    key = cv2.waitKey(1)

    if key == ord('c'):
        # แปลงภาพให้ตรงกับขนาดอินพุตของโมเดล
        img = cv2.resize(frame, input_size)
        img = img.astype(np.float32) / 255.0  # Normalize
        img = np.expand_dims(img, axis=0)  # เพิ่มมิติเป็น [1, 224, 224, 3]

        # ใส่ภาพเข้าโมเดล
        interpreter.set_tensor(input_details[0]['index'], img)
        interpreter.invoke()

        # ดึงผลลัพธ์
        output_data = interpreter.get_tensor(output_details[0]['index'])[0]  # [4]

        print("🎯 ผลลัพธ์การจำแนกขยะ:")
        for i, label in enumerate(class_labels):
            print(f"🔹 {label}: {output_data[i]*100:.2f}%")

        # หาคลาสที่ค่าความน่าจะเป็นสูงสุด
        predicted_class = np.argmax(output_data)

        # แสดงผลลัพธ์ที่คาดการณ์
        print(f"✅ ตรวจพบ: {class_labels[predicted_class]}")

        # ส่งข้อมูลไปยัง MQTT
        client.publish(topic, class_labels[predicted_class])
        print(f"📡 ส่งข้อมูลไปยัง MQTT: {class_labels[predicted_class]}")

    if key == ord('q'):
        break

# ปิดการเชื่อมต่อ
cap.release()
cv2.destroyAllWindows()
client.loop_stop()
client.disconnect()
