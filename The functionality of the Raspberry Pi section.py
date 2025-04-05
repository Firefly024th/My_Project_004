import gspread
from google.oauth2.service_account import Credentials
from oauth2client.service_account import ServiceAccountCredentials
import paho.mqtt.client as mqtt
import RPi.GPIO as GPIO
import time
import datetime

import os
import pickle
import base64
from email.mime.text import MIMEText
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request


receiver_email = "66010024@kmitl.ac.th"
# API Sheet ********************************************************
try:
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file("project-waste-ai-model428-98b2e2d2c90e.json", scopes=scopes)
    client = gspread.authorize(creds)
    sheet_id = "1fxla4XmFjHj9fniZ5YnBkVRg6HqxEsBKUBm2NxqZNo8"
    workbook = client.open_by_key(sheet_id)
    print("✅ เชื่อมต่อ Google Sheets สำเร็จ!")
except Exception as e:
    print(f"❌ เกิดข้อผิดพลาดในการเชื่อมต่อกับ Google Sheets: {e}")
    exit()

# API GMAIL***************************************************
# ชื่อไฟล์ credentials และ token
CREDENTIALS_FILE = "GMAIL_API_WASTE_AI.json"
TOKEN_FILE = "token.pickle"

# Scope สำหรับการส่งอีเมล
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

def authenticate_gmail():
    """ตรวจสอบหรือสร้าง OAuth 2.0 Token"""
    creds = None

    # โหลด Token ที่มีอยู่ ถ้ามี
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as token:
            creds = pickle.load(token)

    # ถ้าไม่มี Token หรือหมดอายุ ให้ขอใหม่
    if not creds or not creds.valid:
        try:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
                creds = flow.run_local_server(port=0)

            # บันทึก Token ใหม่
            with open(TOKEN_FILE, "wb") as token:
                pickle.dump(creds, token)
        except Exception as e:
            print(f"❌ เกิดข้อผิดพลาดในการยืนยันตัวตน: {e}")
            return None
    return creds

# mqtt*********************************************************
# ตั้งค่าตัวแปร
broker = "192.168.43.185"
port = 1883
topic = "Waste"

# ควบคุม Motor ************************************************************
# กำหนดขา GPIO สำหรับ Motor 1 (น้ำเงิน)
IN1_1, IN2_1, IN3_1, IN4_1 = 4, 17, 27, 22

# กำหนดขา GPIO สำหรับ Motor 2 (แดง)
IN1_2, IN2_2, IN3_2, IN4_2 = 11, 5, 6, 26

# ตัวแปรนับขยะ
can_count, plastic_count, general_count, glass_count = 0, 0, 0, 0

# ตั้งค่า GPIO
def setup_gpio():
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    for pin in [IN1_1, IN2_1, IN3_1, IN4_1, IN1_2, IN2_2, IN3_2, IN4_2]:
        GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)

setup_gpio()

# ลำดับการหมุนของ Step Motor
step_sequence = [
    [1, 0, 0, 1], [1, 0, 0, 0], [1, 1, 0, 0], [0, 1, 0, 0],
    [0, 1, 1, 0], [0, 0, 1, 0], [0, 0, 1, 1], [0, 0, 0, 1]
]

# ฟังก์ชันหมุนมอเตอร์
# ฟังก์ชันหมุนมอเตอร์
def rotate(motor, degrees, direction=1, delay=0.001):
    global motor1_position, motor2_position
    motor_pins = (IN1_1, IN2_1, IN3_1, IN4_1) if motor == 1 else (IN1_2, IN2_2, IN3_2, IN4_2)
    steps_per_revolution = 512
    steps = int(steps_per_revolution * abs(degrees) / 360)  # ใช้ abs(degrees) เพื่อให้รองรับทั้งมุมบวกและลบ

    # ตรวจสอบทิศทางการหมุน
    if degrees < 0:
        direction = -1  # ถ้ามุมเป็นลบ ให้หมุนทวนเข็มนาฬิกา

    for _ in range(steps):
        for step in step_sequence[::direction]:
            for pin, val in zip(motor_pins, step):
                GPIO.output(pin, val)
            time.sleep(delay)

    if motor == 1:
        motor1_position = (motor1_position + degrees * direction) % 360
    else:
        motor2_position = (motor2_position + degrees * direction) % 360

# ฟังก์ชันแยกขยะ
def Can():
    global can_count
    rotate(1, 90,-1); time.sleep(1) # -90 เเทนค่า 270
    rotate(2, 45, 1); can_count += 1; time.sleep(1)
    rotate(2, 45, -1); time.sleep(1)
    rotate(1, 90, 1); time.sleep(1)

def Plastic_Bottle():
    global plastic_count
    rotate(1, 90, 1); time.sleep(1)
    rotate(2, 45, 1); plastic_count += 1; time.sleep(1)
    rotate(2, 45, -1); time.sleep(1)
    rotate(1, 90, -1); time.sleep(1)

def General_Waste():
    global general_count
    rotate(2, 45, 1); general_count += 1; time.sleep(1)
    rotate(2, 45, -1); time.sleep(1)

def Glass():
    global glass_count
    rotate(1, 180, 1); time.sleep(1)
    rotate(2, 45, 1); glass_count += 1; time.sleep(1)
    rotate(2, 45, -1); time.sleep(1)
    rotate(1, 180, -1); time.sleep(1)

motor1_position, motor2_position = 0, 0  # กำหนดค่าตั้งต้น

def reset_position():
    global motor1_position, motor2_position
    
    if motor1_position != 0:
        print(f"🔄 รีเซ็ต Motor 1 จากตำแหน่ง {motor1_position} องศา")
        rotate(1, -motor1_position)  # ใช้ค่าตรงข้ามของ motor1_position
        motor1_position = 0
    
    if motor2_position != 0:
        print(f"🔄 รีเซ็ต Motor 2 จากตำแหน่ง {motor2_position} องศา")
        rotate(2, -motor2_position)  # ใช้ค่าตรงข้ามของ motor2_position
        motor2_position = 0
    
    print("✅ มอเตอร์ทั้งหมดรีเซ็ตตำแหน่งเรียบร้อย!")


# Gmail Api*************************************************
def send_email(receiver_email, subject, message_text):
    """ฟังก์ชันส่งอีเมล"""
    creds = authenticate_gmail()
    if not creds:
        print("❌ ไม่สามารถรับรองความถูกต้องของ Gmail API ได้")
        return

    try:
        service = build("gmail", "v1", credentials=creds)

        # สร้างข้อความอีเมล (รองรับ UTF-8)
        message = MIMEText(message_text, "plain", "utf-8")
        message["to"] = receiver_email
        message["subject"] = subject
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

        # ส่งอีเมล
        send_message = service.users().messages().send(
            userId="me", body={"raw": raw_message}
        ).execute()

        print(f"✅ Email sent successfully! (Message ID: {send_message['id']})")

    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดในการส่งอีเมล: {e}")


# ฟังก์ชันการอัปเดตข้อมูลใน Google Sheets
# การใช้งาน Api Sheet ********************************************************
#ใช้งานได้ *********************************************************
#today = input("พิมพ์วันที่ (รูปแบบ DD/MM/YYYY): ")
#today = datetime.datetime.now().strftime("%d/%m/%Y")  # ใช้วันที่ในรูปแบบ วัน/เดือน/ปี

def update_google_sheets(can_count, plastic_count, general_count, glass_count):
    receiver_email = "66010024@kmitl.ac.th"
    try:
        sheet = workbook.worksheet("Sheet1")
        #testวันที่ๆๆ
        #today = input("พิมพ์วันที่ (รูปแบบ DD/MM/YYYY): ")
        today = datetime.datetime.now().strftime("%d/%m/%Y")
        
        # ดึงข้อมูลทั้งหมดจาก Google Sheets
        data = sheet.get_all_values()

        # ตรวจสอบวันที่ในแถวที่มีข้อมูล
        found = False
        new_can_count, new_plastic_count, new_general_count, new_glass_count = can_count, plastic_count, general_count, glass_count  # ตั้งค่าเริ่มต้นเป็นค่าที่รับเข้ามา

        for i, row in enumerate(data):
            if len(row) > 0 and row[0] == today:  # เช็คว่าแถวมีค่ามากพอ และวันที่ตรงกัน
                try:
                    old_can_count = int(row[1]) if len(row) > 1 and row[1].isdigit() else 0
                    old_plastic_count = int(row[2]) if len(row) > 2 and row[2].isdigit() else 0
                    old_general_count = int(row[3]) if len(row) > 3 and row[3].isdigit() else 0
                    old_glass_count = int(row[4]) if len(row) > 4 and row[4].isdigit() else 0
                except ValueError:
                    old_can_count, old_plastic_count, old_general_count, old_glass_count = 0, 0, 0, 0  # ถ้าอ่านค่าไม่ได้ให้ใช้ 0

                new_can_count = old_can_count + can_count
                new_plastic_count = old_plastic_count + plastic_count
                new_general_count = old_general_count + general_count
                new_glass_count = old_glass_count + glass_count

                sheet.update(f'A{i + 1}:E{i + 1}', [[today, new_can_count, new_plastic_count, new_general_count, new_glass_count]])
                print(f"✅ ข้อมูลอัปเดตในแถวที่ {i + 1} Google Sheets เรียบร้อย เเถวเดิม!")
                found = True
                break

        if not found:
            # ถ้าไม่เจอวันที่ ให้เพิ่มแถวใหม่
            sheet.append_row([today, new_can_count, new_plastic_count, new_general_count, new_glass_count])
            print("✅ ข้อมูลอัปเดตในแถวใหม่ Google Sheets เรียบร้อย เเถวใหม่!")


        # การส่ง Gmail
        if new_can_count > 5:
            subject = "เเจ้งเตือนถังขยะประเภทกระป๋องเต็มเเล้ว"
            message_text = "ถังขยะประเภทกระป๋องเต็มเเล้ว !!!!!!! "
            send_email(receiver_email, subject, message_text)

        if new_plastic_count > 5:
            subject = "เเจ้งเตือนถังขยะประเภทขวดพลาสติกเต็มเเล้ว"
            message_text = "ถังขยะประเภทขวดพลาสติกเต็มเเล้ว !!!!!!! "
            send_email(receiver_email, subject, message_text)

        if new_general_count > 5:
            subject = "เเจ้งเตือนถังขยะประเภทขยะทั่วไปเต็มเเล้ว"
            message_text = "ถังขยะประเภทขยะทั่วไปเต็มเเล้ว !!!!!!! "
            send_email(receiver_email, subject, message_text)

        if new_glass_count > 5:
            subject = "เเจ้งเตือนถังขยะประเภทเเก้วน้ำเต็มเเล้ว"
            message_text = "ถังขยะประเภทเเก้วน้ำเต็มเเล้ว !!!!!!! "
            send_email(receiver_email, subject, message_text)

    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดในการอัปเดตข้อมูล Google Sheets: {e}")



#เริ่มต้น การทำงาน  ****************************************************************
# การส่ง Email **************************************************
#plastic_count, glass_count, bag_count, general_count = 10, 10, 10, 10
#receiver_email, subject, message_text

# กำหนดตัวแปรสถานะ
has_reset = False  

# รีเซ็ตตำแหน่งมอเตอร์แค่ครั้งแรกที่รันโค้ด
if not has_reset:
    reset_position()
    print("✅ Motor รีเซ็ตตำแหน่งเรียบร้อย! รอรับข้อมูลจาก MQTT...")
    has_reset = True  # กำหนดให้รีเซ็ตแค่ครั้งเดียว

# ฟังก์ชันเมื่อได้รับข้อความ
def on_message(client, userdata, msg):
    global can_count, plastic_count, general_count, glass_count
    command = msg.payload.decode()
    if command == "Can":
        print("กำลังทำงานในส่วน กระป๋อง")
        Can()
        # อัปเดตข้อมูลใน Google Sheets
        update_google_sheets(can_count, plastic_count, general_count, glass_count)
        can_count, plastic_count, general_count, glass_count = 0, 0, 0, 0



    elif command == "Plastic_Bottle":
        print("กำลังทำงานในส่วน ขวดพลาสติก")
        Plastic_Bottle()
        update_google_sheets(can_count, plastic_count, general_count, glass_count)
        can_count, plastic_count, general_count, glass_count = 0, 0, 0, 0


        
    elif command == "General_Waste":
        print("กำลังทำงานในส่วน ขยะทั่วไป")
        General_Waste()
        update_google_sheets(can_count, plastic_count, general_count, glass_count)
        can_count, plastic_count, general_count, glass_count = 0, 0, 0, 0



    elif command == "Glass":
        print("กำลังทำงานในส่วน เเก้วน้ำ")
        Glass()
        update_google_sheets(can_count, plastic_count, general_count, glass_count)
        can_count, plastic_count, general_count, glass_count = 0, 0, 0, 0



# mqtt****************************************************
try:
    #client = mqtt.Client() อันเก่า
    client = mqtt.Client(protocol=mqtt.MQTTv5)
    client.on_message = on_message
    client.connect(broker, port, 60)
    client.subscribe(topic)
    #client.loop_forever()  อันเก่าา

    while True:
        try:
            client.loop_forever()
        except Exception as e:
            print(f"⚠️ การเชื่อมต่อ MQTT หลุด: {e}")
            time.sleep(5)  # รอ 5 วินาทีก่อนลองใหม่
            client.reconnect()

except KeyboardInterrupt:
    print("\n🛑 หยุดการทำงาน")
finally:
    GPIO.cleanup()