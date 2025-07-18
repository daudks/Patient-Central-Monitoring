
import eventlet



from flask import Flask, request, jsonify, render_template, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit
from datetime import datetime
import pandas as pd
import io
from flask_migrate import Migrate
eventlet.monkey_patch()
# === Flask & SocketIO Setup ===
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///medical_data.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
import threading
import time
import random
from flask_socketio import SocketIO
import serial

socketio = SocketIO(app)
db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Initialize migrate
migrate = Migrate(app, db)

# === MODELS ===
class Vitals(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.String(100))
    heart_rate = db.Column(db.Integer)
    spo2 = db.Column(db.Float)
    temperature = db.Column(db.Float)
    respiratory_rate = db.Column(db.Integer)
    blood_pressure = db.Column(db.String(20))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class VentilatorData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.String(100))
    oxygen_level = db.Column(db.Float)
    peep = db.Column(db.Float)
    tidal_volume = db.Column(db.Float)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()

# === ROUTES ===
@app.route("/")
def home():
    return render_template("index.html")

@socketio.on('connect')
def handle_connect():
    print("Client connected")
    emit('response', {'data': 'Connected to server'})

@app.route('/api/vitals', methods=['POST'])
def receive_vitals():
    data = request.get_json()
    try:
        vitals = Vitals(
            patient_id=data['patient_id'],
            heart_rate=data.get('heart_rate'),
            spo2=data.get('spo2'),
            temperature=data.get('temperature'),
            respiratory_rate=data.get('respiratory_rate'),
            blood_pressure=data.get('blood_pressure')
        )

        if not all([vitals.patient_id, vitals.heart_rate, vitals.temperature, vitals.respiratory_rate]):
            return jsonify({'error': 'Missing required fields'}), 400

        db.session.add(vitals)
        db.session.commit()

        socketio.emit('new_vitals', {
            'patient_id': vitals.patient_id,
            'heart_rate': vitals.heart_rate,
            'spo2': vitals.spo2,
            'temperature': vitals.temperature,
            'respiratory_rate': vitals.respiratory_rate,
            'blood_pressure': vitals.blood_pressure,
            'timestamp': vitals.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        })

        return jsonify({'message': 'Vitals recorded and broadcasted'}), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/api/ventilator', methods=['POST'])
def receive_ventilator_data():
    data = request.get_json()
    vent_data = VentilatorData(
        patient_id=data.get('patient_id'),
        oxygen_level=data.get('oxygen_level'),
        peep=data.get('peep'),
        tidal_volume=data.get('tidal_volume')
    )
    db.session.add(vent_data)
    db.session.commit()
    return jsonify({'message': 'Ventilator data recorded'}), 201

@app.route('/vitals')
def get_vitals():
    vitals = Vitals.query.all()
    return jsonify([{
        'id': v.id,
        'patient_id': v.patient_id,
        'heart_rate': v.heart_rate,
        'blood_pressure': v.blood_pressure,
        'spo2': v.spo2,
        'temperature': v.temperature,
        'respiratory_rate': v.respiratory_rate,
        'timestamp': v.timestamp.isoformat()
    } for v in vitals])

@app.route('/ventilator')
def get_ventilator_data():
    vents = VentilatorData.query.all()
    return jsonify([{
        'id': v.id,
        'patient_id': v.patient_id,
        'oxygen_level': v.oxygen_level,
        'peep': v.peep,
        'tidal_volume': v.tidal_volume,
        'timestamp': v.timestamp.isoformat()
    } for v in vents])

# === Dashboard View ===
@app.route('/dashboard')
def dashboard():
    patient_id = request.args.get('patient_id')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    vitals_query = Vitals.query
    ventilator_query = VentilatorData.query

    if patient_id:
        vitals_query = vitals_query.filter(Vitals.patient_id.ilike(f"%{patient_id}%"))
        ventilator_query = ventilator_query.filter(VentilatorData.patient_id.ilike(f"%{patient_id}%"))

    def parse_date(date_str):
        try:
            return datetime.strptime(date_str, '%Y-%m-%d')
        except:
            return None

    start = parse_date(start_date)
    end = parse_date(end_date)
    if start:
        vitals_query = vitals_query.filter(Vitals.timestamp >= start)
        ventilator_query = ventilator_query.filter(VentilatorData.timestamp >= start)
    if end:
        end = end.replace(hour=23, minute=59, second=59)
        vitals_query = vitals_query.filter(Vitals.timestamp <= end)
        ventilator_query = ventilator_query.filter(VentilatorData.timestamp <= end)

    vitals = vitals_query.order_by(Vitals.timestamp.desc()).limit(50).all()
    ventilator = ventilator_query.order_by(VentilatorData.timestamp.desc()).limit(50).all()

    return render_template('dashboard.html', vitals=vitals, ventilator=ventilator)

# === Export to Excel ===
@app.route('/export_excel')
def export_excel():
    vitals = Vitals.query.order_by(Vitals.timestamp.desc()).all()
    ventilator = VentilatorData.query.order_by(VentilatorData.timestamp.desc()).all()

    vitals_df = pd.DataFrame([{
        'Patient ID': v.patient_id,
        'Heart Rate': v.heart_rate,
        'SpO2': v.spo2,
        'Temperature': v.temperature,
        'Respiratory Rate': v.respiratory_rate,
        'Blood Pressure': v.blood_pressure,
        'Timestamp': v.timestamp
    } for v in vitals])

    ventilator_df = pd.DataFrame([{
        'Patient ID': v.patient_id,
        'Oxygen Level': v.oxygen_level,
        'PEEP': v.peep,
        'Tidal Volume': v.tidal_volume,
        'Timestamp': v.timestamp
    } for v in ventilator])

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        vitals_df.to_excel(writer, sheet_name='Vitals', index=False)
        ventilator_df.to_excel(writer, sheet_name='Ventilator', index=False)

    output.seek(0)
    return send_file(output, as_attachment=True, download_name='medical_data.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

# === Real-time Chart API ===
@app.route('/api/chart_data')
def chart_data():
    vitals = Vitals.query.order_by(Vitals.timestamp.asc()).limit(20).all()
    ventilator = VentilatorData.query.order_by(VentilatorData.timestamp.asc()).limit(20).all()

    return jsonify({
        'vitals': {
            'timestamps': [v.timestamp.strftime('%H:%M:%S') for v in vitals],
            'heart_rate': [v.heart_rate for v in vitals],
            'spo2': [v.spo2 for v in vitals],
            'temperature': [v.temperature for v in vitals],
            'respiratory_rate': [v.respiratory_rate for v in vitals],
        },
        'ventilator': {
            'timestamps': [v.timestamp.strftime('%H:%M:%S') for v in ventilator],
            'oxygen_level': [v.oxygen_level for v in ventilator],
            'peep': [v.peep for v in ventilator],
            'tidal_volume': [v.tidal_volume for v in ventilator],
        }
    })
def generate_fake_vitals():
    while True:
        fake_data = {
            "patient_id": "sim123",
            "heart_rate": random.randint(60, 110),
            "spo2": random.randint(88, 100),
            "temperature": round(random.uniform(36.0, 38.5), 1),
            "respiratory_rate": random.randint(12, 28),
            "blood_pressure": f"{random.randint(110, 150)}/{random.randint(70, 95)}",
            "timestamp": time.strftime('%Y-%m-%d %H:%M:%S')
        }
        socketio.emit('new_vitals', fake_data)
        print("[SIMULATION] Sending vitals:", fake_data)  # Debug print
        socketio.emit('vitals_update', fake_data)
        time.sleep(5)

# Start the simulation thread on server start
def start_simulation():
    thread = threading.Thread(target=generate_fake_vitals)
    thread.daemon = True
    thread.start()


# Example serial port settings — adjust as needed for your device
#SERIAL_PORT = 'COM3'  # Change to your actual device port
#BAUD_RATE = 9600
#def read_serial_data():
    #try:
        #ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        #print("✅ Serial port connected...")
        #while True:
            #if ser.in_waiting:
                #line = ser.readline().decode('utf-8').strip()
                # Parse incoming line, e.g. "HR:78|BP:120/80|SpO2:98|TEMP:36.7"
                #parts = dict(x.split(":") for x in line.split("|"))
                # Emit data to dashboard
                #socketio.emit('vitals_update', parts)
            #time.sleep(0.5)
   # except Exception as e:
        #print("❌ Serial connection error:", e)

# Start background thread when server starts
#threading.Thread(target=read_serial_data, daemon=True).start()
# === Run App ===
if __name__ == '__main__':
    start_simulation()
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
