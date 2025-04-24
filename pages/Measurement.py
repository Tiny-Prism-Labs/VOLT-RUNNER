import streamlit as st
import pyvisa
import serial
import time
import datetime
import csv
import pandas as pd
import matplotlib.pyplot as plt
import os
import threading
import sqlite3 # Import SQLite
import contextlib # For managing DB connection/cursor

# --- Configuration ---
DB_FILE = "Database/VoltRunner.db"
DEFAULT_PSU_PORT = '/dev/ttyUSB0'; DEFAULT_METER_PORT = '/dev/ttyACM0'
DEFAULT_VOLTAGE = 3.7; DEFAULT_CURRENT_LIMIT = 1.0
DEFAULT_DURATION = 10; DATA_RECORD_INTERVAL_SEC = 1.0
UI_REFRESH_INTERVAL_SEC = 0.75

# --- Database Setup ---
def init_db():
    """Initializes the SQLite database and tables if they don't exist."""
    with contextlib.closing(sqlite3.connect(DB_FILE)) as db:
        with db: # Auto-commit/rollback context
            db.execute('''
                CREATE TABLE IF NOT EXISTS status (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            db.execute('''
                CREATE TABLE IF NOT EXISTS live_measurements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    elapsed_seconds REAL,
                    voltage REAL,
                    current REAL
                )
            ''')
            db.execute("INSERT OR IGNORE INTO status (key, value) VALUES ('is_running', '0')")
            db.execute("INSERT OR IGNORE INTO status (key, value) VALUES ('status_text', 'Idle')")
            db.execute("INSERT OR IGNORE INTO status (key, value) VALUES ('remaining_time', '0')")
            db.execute("INSERT OR IGNORE INTO status (key, value) VALUES ('last_error', '')")
            db.execute("INSERT OR IGNORE INTO status (key, value) VALUES ('current_csv_filename', '')")
            db.execute("INSERT OR IGNORE INTO status (key, value) VALUES ('psu_idn', 'N/A')")
            db.execute("INSERT OR IGNORE INTO status (key, value) VALUES ('meter_port_name', 'N/A')")
            db.execute("INSERT OR IGNORE INTO status (key, value) VALUES ('plot_ready', '0')")

def update_status(key, value):
    """Updates a key-value pair in the status table."""
    try:
        with contextlib.closing(sqlite3.connect(DB_FILE, timeout=10)) as db:
            with db:
                db.execute("INSERT OR REPLACE INTO status (key, value) VALUES (?, ?)", (key, str(value)))
    except sqlite3.Error as e:
        print(f"DB ERROR updating status {key}={value}: {e}")

def get_status(key):
    """Gets a value from the status table."""
    val = None
    try:
        with contextlib.closing(sqlite3.connect(DB_FILE, timeout=10)) as db:
            cursor = db.execute("SELECT value FROM status WHERE key = ?", (key,))
            result = cursor.fetchone()
            if result: val = result[0]
    except sqlite3.Error as e: print(f"DB ERROR getting status {key}: {e}")
    return val

def add_live_data(elapsed_seconds, voltage, current):
     """Adds a row to the live_measurements table."""
     try:
         with contextlib.closing(sqlite3.connect(DB_FILE, timeout=10)) as db:
             with db:
                 db.execute("INSERT INTO live_measurements (elapsed_seconds, voltage, current) VALUES (?, ?, ?)",
                            (elapsed_seconds, voltage, current))
     except sqlite3.Error as e: print(f"DB ERROR adding live data: {e}")

def clear_live_data():
    """Deletes all data from the live_measurements table."""
    try:
        with contextlib.closing(sqlite3.connect(DB_FILE, timeout=10)) as db:
            with db:
                db.execute("DELETE FROM live_measurements")
                # Reset autoincrement (optional, good practice after DELETE)
                db.execute("DELETE FROM sqlite_sequence WHERE name='live_measurements'")
    except sqlite3.Error as e: print(f"DB ERROR clearing live data: {e}")

def get_live_data_df():
    """Retrieves all live data as a Pandas DataFrame."""
    df = pd.DataFrame({'Elapsed Time (s)':[], 'Voltage (V)':[], 'Current (A)':[]}) # Default empty
    try:
        with contextlib.closing(sqlite3.connect(DB_FILE, timeout=10)) as db:
             df = pd.read_sql_query("SELECT elapsed_seconds as 'Elapsed Time (s)', voltage as 'Voltage (V)', current as 'Current (A)' FROM live_measurements ORDER BY id ASC", db)
    except sqlite3.Error as e: print(f"DB ERROR reading live data: {e}")
    except Exception as ex: print(f"Error converting live data to DataFrame: {ex}")
    return df

# --- Run DB Init Once ---
init_db()

# --- Device Communication Functions (remain the same) ---
def connect_psu(resource_string, baud_rate):
    rm = pyvisa.ResourceManager('@py'); psu = rm.open_resource(resource_string, baud_rate=baud_rate, data_bits=8, parity=pyvisa.constants.Parity.none, stop_bits=pyvisa.constants.StopBits.one)
    psu.read_termination='\n'; psu.write_termination='\n'; psu.timeout=5000; return rm, psu
def connect_meter(port, baud_rate, timeout):
    meter = serial.Serial(port, baud_rate, serial.EIGHTBITS, serial.PARITY_NONE, serial.STOPBITS_ONE, timeout=timeout); return meter
def setup_psu(psu, voltage, current_limit):
    psu.write(f'VOLTage {voltage}'); time.sleep(0.2); psu.write(f'CURRent {current_limit}'); time.sleep(0.2)
def setup_meter(meter):
    meter.write(b":FUNCtion:mode DC\n"); time.sleep(0.1); meter.write(b":FUNCtion:ENERgy reset\n"); time.sleep(0.1); meter.write(b":FUNCtion:ecmode MAN\n"); time.sleep(0.1)
    now=datetime.datetime.now(); year=now.strftime("%y"); month=now.strftime("%m"); day=now.strftime("%d"); hour=now.strftime("%H"); minute=now.strftime("%M"); second=now.strftime("%S")
    meter.write(f":SYSTem:year {year}\n".encode('utf-8')); time.sleep(0.05); meter.write(f":SYSTem:MONth {month}\n".encode('utf-8')); time.sleep(0.05)
    meter.write(f":SYSTem:date {day}\n".encode('utf-8')); time.sleep(0.05); meter.write(f":SYSTem:hour {hour}\n".encode('utf-8')); time.sleep(0.05)
    meter.write(f":SYSTem:MINute {minute}\n".encode('utf-8')); time.sleep(0.05); meter.write(f":SYSTem:SECond {second}\n".encode('utf-8')); time.sleep(0.2)


# --- Background Test Function (Corrected Finally Block) ---
def run_measurement_test_db(psu_port, meter_port, voltage, current_limit, duration, stop_event):
    """Writes status/data to DB, writes final CSV."""
    psu = None; meter = None; rm = None; csv_writer = None; csv_file = None
    test_start_time = 0; final_status = "Unknown"; error_msg = ""
    final_filename = f"csv/PSU_Meter_Test_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    update_status('status_text', 'Connecting...'); update_status('current_csv_filename', final_filename)
    update_status('last_error', '')

    try:
        print("THREAD: Connecting..."); rm, psu = connect_psu(f'ASRL{psu_port}::INSTR', 115200); meter = connect_meter(meter_port, 115200, 2)
        print("THREAD: Devices Connected.")
        try: psu_idn = psu.query('*IDN?'); update_status('psu_idn', psu_idn.strip())
        except Exception: update_status('psu_idn', 'IDN Failed')
        update_status('meter_port_name', meter.name); print(f"THREAD: Meter Connected: {meter.name}")
        update_status('status_text', 'Configuring...')

        print("THREAD: Configuring..."); setup_psu(psu, voltage, current_limit); setup_meter(meter); print("THREAD: Configured.")
        print("THREAD: Turning PSU ON..."); psu.write('OUTPut ON'); time.sleep(1); print("THREAD: PSU ON.")
        print("THREAD: Starting Meter..."); meter.write(b":FUNCtion:ENERgy run\n"); time.sleep(0.1)

        update_status('status_text', 'Running...'); test_start_time = time.time()

        print(f"THREAD: Opening Final CSV: {final_filename}")
        with open(final_filename, 'w', newline='') as csv_file:
            csv_writer = csv.writer(csv_file)
            csv_writer.writerow(['Timestamp', 'Elapsed Time (s)', 'Voltage (V)', 'Current (A)', 'Power (W)', 'Energy (Wh)'])
            print("THREAD: Final CSV Header Written.")

            while not stop_event.is_set():
                loop_start_time = time.time() # Defined here
                elapsed_seconds = loop_start_time - test_start_time
                if elapsed_seconds >= duration: print("THREAD: Duration reached."); break

                timestamp_dt = datetime.datetime.now()
                timestamp_str = timestamp_dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

                try:
                    v_val, i_val, p_val, e_val = None, None, None, None
                    meter.reset_input_buffer()
                    meter.write(b":FETCh VOLTage\n"); time.sleep(0.1)
                    if meter.in_waiting > 0: v_val = float(meter.readline().decode('utf-8').strip())
                    meter.reset_input_buffer()
                    meter.write(b":FETCh CURRent\n"); time.sleep(0.1)
                    if meter.in_waiting > 0: i_val = float(meter.readline().decode('utf-8').strip())
                    meter.reset_input_buffer()
                    meter.write(b":FETCh power\n"); time.sleep(0.1)
                    if meter.in_waiting > 0: p_val = float(meter.readline().decode('utf-8').strip())
                    meter.reset_input_buffer()
                    meter.write(b":FETCh energy\n"); time.sleep(0.1)
                    if meter.in_waiting > 0: e_val = float(meter.readline().decode('utf-8').strip())

                    # Write to final CSV directly
                    csv_writer.writerow([timestamp_str, f"{elapsed_seconds:.3f}",
                                         v_val if v_val is not None else 'N/A', i_val if i_val is not None else 'N/A',
                                         p_val if p_val is not None else 'N/A', e_val if e_val is not None else 'N/A'])

                    # Add V/I/Elapsed to live DB table
                    if v_val is not None and i_val is not None:
                         add_live_data(elapsed_seconds, v_val, i_val)

                except (ValueError, serial.SerialException, pyvisa.errors.VisaIOError, Exception) as meas_err:
                    error_type = type(meas_err).__name__; print(f"THREAD: ERROR ({error_type}): {meas_err}")
                    csv_writer.writerow([timestamp_str, f"{elapsed_seconds:.3f}", 'ERROR', 'ERROR', 'ERROR', 'ERROR'])
                    if isinstance(meas_err, (serial.SerialException, pyvisa.errors.VisaIOError)):
                        error_msg = f"{error_type}: {meas_err}"; final_status = "Error"; break

                remaining = max(0, duration - elapsed_seconds)
                update_status('remaining_time', remaining) # Update DB

                loop_end_time = time.time(); elapsed_time_this_loop = loop_end_time - loop_start_time
                wait_time = max(0, DATA_RECORD_INTERVAL_SEC - elapsed_time_this_loop)
                stop_event.wait(wait_time) # Use stop event for waiting
        # --- End of loop ---
        if stop_event.is_set(): print("THREAD: Stop event."); final_status = "Stopped"
        elif final_status != "Error": final_status = "Finished"

    except (serial.SerialException, pyvisa.errors.VisaIOError, Exception) as conn_err:
        error_type = type(conn_err).__name__; error_msg = f"Conn/Setup Error ({error_type}): {conn_err}"
        print(f"THREAD: FATAL ERROR: {error_msg}"); final_status = "Error"
    finally:
        # --- Cleanup (Corrected Syntax) ---
        print("THREAD: Cleanup sequence started...")

        # Cleanup Meter
        if meter:
            try:
                print("THREAD: Stopping meter energy...")
                meter.write(b":FUNCtion:ENERgy stop\n") # Each command on its own line
                time.sleep(0.1)
                print("THREAD: Resetting meter energy...")
                meter.write(b":FUNCtion:ENERgy reset\n")
                time.sleep(0.1)
                print("THREAD: Closing meter port...")
                meter.close()
                print("THREAD: Meter closed.")
            except Exception as e_meter_close:
                print(f"THREAD: Meter cleanup error: {e_meter_close}")

        # Cleanup PSU
        if psu:
            try:
                print("THREAD: Turning PSU OFF...")
                psu.write('OUTPut OFF') # Each command on its own line
                time.sleep(0.2)
                print("THREAD: Closing PSU port...")
                psu.close()
                print("THREAD: PSU closed.")
            except Exception as e_psu_close:
                print(f"THREAD: PSU cleanup/OFF error: {e_psu_close}")

        # Cleanup Resource Manager
        if rm:
            try:
                print("THREAD: Closing VISA RM...")
                rm.close() # Command on its own line
                print("THREAD: VISA RM closed.")
            except Exception as e_rm_close:
                print(f"THREAD: RM close error: {e_rm_close}")

        # --- Update final status in DB ---
        print(f"THREAD: Updating final status: {final_status}")
        update_status('status_text', final_status)
        update_status('is_running', '0') # Set running to false
        update_status('remaining_time', '0')
        if error_msg: update_status('last_error', error_msg)
        if final_status == "Finished": update_status('plot_ready', '1')
        else: update_status('plot_ready', '0')
        print("THREAD: Finished.")


# --- Streamlit App UI ---
st.set_page_config(layout="wide")
st.title("⚡ VOLT/RUNNER Live Feed")

# --- Initialize Session State (Local display state) ---
if 'live_data_df' not in st.session_state:
    st.session_state.live_data_df = pd.DataFrame({'Elapsed Time (s)':[], 'Voltage (V)':[], 'Current (A)':[]})
if 'current_status' not in st.session_state:
     st.session_state.current_status = "Idle" # Track status locally to manage reruns
if 'stop_event' not in st.session_state: st.session_state.stop_event = None # Init stop event ref


# --- Get Global State from DB ---
is_globally_running = get_status('is_running') == '1'
current_status_db = get_status('status_text') or "Idle"
remaining_time_db = float(get_status('remaining_time') or 0)
psu_idn_db = get_status('psu_idn') or "N/A"
meter_port_db = get_status('meter_port_name') or "N/A"
last_error_db = get_status('last_error') or ""
current_csv_db = get_status('current_csv_filename') or ""
plot_ready_db = get_status('plot_ready') == '1'

# Update local session state if DB status changed
if st.session_state.current_status != current_status_db:
     st.session_state.current_status = current_status_db
     if current_status_db not in ["Running..."]: # Clear local live data if test not running
          st.session_state.live_data_df = pd.DataFrame({'Elapsed Time (s)':[], 'Voltage (V)':[], 'Current (A)':[]})


# --- Input Controls (Sidebar) ---
with st.sidebar:
    st.header("Configuration")
    psu_port_input = st.text_input("PSU Serial Port", value=DEFAULT_PSU_PORT, disabled=is_globally_running)
    meter_port_input = st.text_input("Meter Serial Port", value=DEFAULT_METER_PORT, disabled=is_globally_running)
    voltage_input = st.number_input("Target Voltage (V)", 0.0, 60.0, DEFAULT_VOLTAGE, 0.1, "%.1f", disabled=is_globally_running)
    current_limit_input = st.number_input("Current Limit (A)", 0.0, 10.0, DEFAULT_CURRENT_LIMIT, 0.1, "%.1f", disabled=is_globally_running)
    duration_input = st.number_input("Test Duration (s)", 1, 3600*24, DEFAULT_DURATION, 1, disabled=is_globally_running)
    col1, col2 = st.columns(2);
    with col1: start_button = st.button("Start Test", disabled=is_globally_running, type="primary", use_container_width=True)
    with col2: stop_button = st.button("Stop Test", disabled=not is_globally_running, use_container_width=True)

# --- Status Display (Reads from DB values fetched above) ---
st.header("Status of the Device")
status_cols = st.columns(3); status_placeholder = status_cols[0].empty()
timer_placeholder = status_cols[1].empty(); info_placeholder = status_cols[2].empty()
error_placeholder = st.empty(); success_placeholder = st.empty()
status_placeholder.metric("Test Status", current_status_db)
timer_placeholder.metric("Time Remaining", f"{remaining_time_db:.0f} s")
info_placeholder.info(f"PSU: {psu_idn_db}\nMeter: {meter_port_db}")
if last_error_db: error_placeholder.error(f"Error Encountered: {last_error_db}")
else: error_placeholder.empty()
if current_status_db == "Finished" and current_csv_db: success_placeholder.success(f"Test finished. Data saved to: {current_csv_db}")
else: success_placeholder.empty()

# --- Live Plot Placeholders ---
st.header("Live Measurements")
col1, col2 = st.columns(2)
with col1: st.subheader("Voltage (V) vs Time (s)"); voltage_plot_placeholder = st.empty()
with col2: st.subheader("Current (A) vs Time (s)"); current_plot_placeholder = st.empty()

# --- Update Live Plots (if running) ---
if is_globally_running:
     live_df_from_db = get_live_data_df() # Read latest live data from DB
     st.session_state.live_data_df = live_df_from_db # Update local copy for display

# Update plots from local session state (which was just updated from DB if running)
voltage_plot_placeholder.line_chart(st.session_state.live_data_df, x='Elapsed Time (s)', y='Voltage (V)')
current_plot_placeholder.line_chart(st.session_state.live_data_df, x='Elapsed Time (s)', y='Current (A)')

# --- Button Actions (Interact with DB) ---
if start_button:
    # Double check DB status before starting
    if get_status('is_running') == '0':
        update_status('is_running', '1'); update_status('status_text', 'Starting...')
        update_status('last_error', ''); update_status('plot_ready', '0')
        update_status('current_csv_filename', '') # Clear old filename
        clear_live_data() # Clear previous live data from DB table
        st.session_state.stop_event = threading.Event() # Create local stop event

        # Reset local display state immediately
        st.session_state.current_status = "Starting..."
        st.session_state.live_data_df = pd.DataFrame({'Elapsed Time (s)':[], 'Voltage (V)':[], 'Current (A)':[]})

        # Start thread
        thread = threading.Thread(target=run_measurement_test_db,
            args=(psu_port_input, meter_port_input, voltage_input, current_limit_input, duration_input,
                  st.session_state.stop_event), daemon=True) # Pass local event
        thread.start(); print("MAIN: Start button pressed, thread started.")
        time.sleep(0.1) # Brief pause to allow thread to start and update status
        st.rerun()
    else: st.warning("A test is already running (DB status).")

if stop_button:
    # Signal stop event if it exists in session state
    if st.session_state.stop_event:
         update_status('status_text', 'Stopping...') # Update DB status
         st.session_state.current_status = "Stopping..." # Update local status immediately
         st.session_state.stop_event.set()
         print("MAIN: Stop button pressed.")
         st.session_state.stop_event = None # Clear local event ref
         st.rerun()
    else:
        # If stop event doesn't exist locally, maybe test was started by another session.
        # We can still try to update the global status, but can't signal the event.
        # This highlights a limitation of managing the event locally.
        # A truly robust solution might store a 'stop_requested' flag in the DB.
        print("MAIN: Stop pressed, but no local stop event found (test likely started elsewhere).")
        update_status('status_text', 'Stopping...') # Attempt global status update
        st.session_state.current_status = "Stopping..."
        st.rerun()


# --- Schedule Rerun if Test is Globally Running ---
if is_globally_running:
    time.sleep(UI_REFRESH_INTERVAL_SEC)
    # print("MAIN: Rerunning for live update check...") # Debug
    st.rerun()

# --- Post-Run Plotting (Checks DB flag) ---
if plot_ready_db and current_csv_db and os.path.exists(current_csv_db):
    st.header("Final Test Results Plot")
    if os.path.getsize(current_csv_db) > 50:
        try:
            df = pd.read_csv(current_csv_db, header=0)
            if 'Timestamp' not in df.columns or 'Voltage (V)' not in df.columns or 'Current (A)' not in df.columns: raise ValueError("CSV missing cols")
            df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce'); df['Voltage (V)'] = pd.to_numeric(df['Voltage (V)'], errors='coerce'); df['Current (A)'] = pd.to_numeric(df['Current (A)'], errors='coerce')
            df.dropna(subset=['Timestamp', 'Voltage (V)', 'Current (A)'], inplace=True)
            if not df.empty:
                fig, ax1 = plt.subplots(figsize=(12, 5))
                color='tab:red'; ax1.set_xlabel('Time'); ax1.set_ylabel('Voltage (V)', color=color); ax1.plot(df['Timestamp'], df['Voltage (V)'], color=color); ax1.tick_params(axis='y', labelcolor=color); ax1.grid(True, axis='y', linestyle='--', alpha=0.6); ax1.tick_params(axis='x', rotation=45)
                ax2 = ax1.twinx(); color='tab:blue'; ax2.set_ylabel('Current (A)', color=color); ax2.plot(df['Timestamp'], df['Current (A)'], color=color); ax2.tick_params(axis='y', labelcolor=color)
                plt.title(f'Test Results (V & I) - {os.path.basename(current_csv_db)}'); fig.tight_layout(); st.pyplot(fig)
            else: st.warning("Plotting skipped: No valid numeric data in CSV.")
        except pd.errors.EmptyDataError: st.error(f"Plotting Error: CSV file '{current_csv_db}' seems empty.")
        except FileNotFoundError: st.error(f"Plotting Error: File '{current_csv_db}' not found.")
        except Exception as e_plot: st.error(f"Plotting Error: {e_plot}")
    else: st.warning(f"Plotting skipped: CSV file '{current_csv_db}' is empty/small.")