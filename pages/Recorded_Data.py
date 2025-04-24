import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import os
import datetime

# Set the directory where the CSV files are located
csv_directory = '/home/tpl/Projects/DigitalPowerMeter/csv'

# Get a list of all CSV files in the directory
csv_files = [f for f in os.listdir(csv_directory) if f.endswith('.csv')]

st.title('⚡ VOLT/RUNNER Data Archives')

st.sidebar.header('Plotting Options')
selected_filename = st.sidebar.selectbox('Select a CSV file', csv_files)
plot_custom_duration = st.sidebar.checkbox('Plot Custom Duration')

start_minute = None
end_minute = None

if plot_custom_duration:
    start_minute = st.sidebar.number_input('Start Time (minutes)', min_value=0, step=1)
    end_minute = st.sidebar.number_input('End Time (minutes)', min_value=0, step=1)

st.sidebar.header('Battery Estimation')
battery_nominal_voltage = st.sidebar.number_input('Nominal Battery Voltage (V)', value=3.7)
battery_capacity_mah = st.sidebar.number_input('Battery Capacity (mAh)', value=300)

if not csv_files:
    st.warning(f"No CSV files found in the directory: {csv_directory}")
else:
    filepath = os.path.join(csv_directory, selected_filename)

    try:
        df = pd.read_csv(filepath)
        if 'Timestamp' in df.columns:
            df['Timestamp'] = pd.to_datetime(df['Timestamp'])
            df = df.set_index('Timestamp')

        df['Current (mA)'] = df['Current (A)'] * 1000
        df['Power (mW)'] = df['Power (W)'] * 1000
        # df['Energy (mWh)'] = df['Energy (Wh)'] * 1000 # Energy section commented out

        if plot_custom_duration and start_minute is not None and end_minute is not None:
            start_time = df.index.min() + pd.Timedelta(minutes=start_minute)
            end_time = df.index.min() + pd.Timedelta(minutes=end_minute)
            df_filtered = df[(df.index >= start_time) & (df.index <= end_time)]
        else:
            df_filtered = df

        if not df_filtered.empty:
            # --- Voltage Plot and Stats ---
            st.subheader('Voltage (V)')
            fig_voltage, ax_voltage = plt.subplots(figsize=(12, 6)) # Increased figure size
            ax_voltage.plot(df_filtered.index, df_filtered['Voltage (V)'])
            ax_voltage.set_xlabel('Time')
            ax_voltage.set_ylabel('Voltage (V)')
            ax_voltage.grid(True)
            st.pyplot(fig_voltage)
            voltage_stats = df_filtered['Voltage (V)'].agg(['max', 'min', 'mean']).round(3)
            st.write(f"Max Voltage: {voltage_stats['max']} V, Min Voltage: {voltage_stats['min']} V, Average Voltage: {voltage_stats['mean']} V")

            # --- Current Plot and Stats ---
            st.subheader('Current (mA)')
            fig_current, ax_current = plt.subplots(figsize=(12, 6)) # Increased figure size
            ax_current.plot(df_filtered.index, df_filtered['Current (mA)'])
            ax_current.set_xlabel('Time')
            ax_current.set_ylabel('Current (mA)')
            ax_current.grid(True)
            st.pyplot(fig_current)
            current_stats = df_filtered['Current (mA)'].agg(['max', 'min', 'mean']).round(3)
            st.write(f"Max Current: {current_stats['max']} mA, Min Current: {current_stats['min']} mA, Average Current: {current_stats['mean']} mA")

            # --- Power Plot and Stats ---
            st.subheader('Power (mW)')
            fig_power, ax_power = plt.subplots(figsize=(12, 6)) # Increased figure size
            ax_power.plot(df_filtered.index, df_filtered['Power (mW)'])
            ax_power.set_xlabel('Time')
            ax_power.set_ylabel('Power (mW)')
            ax_power.grid(True)
            st.pyplot(fig_power)
            power_stats = df_filtered['Power (mW)'].agg(['max', 'min', 'mean']).round(3)
            st.write(f"Max Power: {power_stats['max']} mW, Min Power: {power_stats['min']} mW, Average Power: {power_stats['mean']} mW")

            # --- YY Plot of Voltage and Current ---
            st.subheader('Voltage (V) and Current (mA) Over Time')
            fig_yy, ax1 = plt.subplots(figsize=(12, 6))

            color = 'tab:red'
            ax1.set_xlabel('Time')
            ax1.set_ylabel('Voltage (V)', color=color)
            ax1.plot(df_filtered.index, df_filtered['Voltage (V)'], color=color)
            ax1.tick_params(axis='y', labelcolor=color)

            ax2 = ax1.twinx()  # instantiate a second axes that shares the same x-axis

            color = 'tab:blue'
            ax2.set_ylabel('Current (mA)', color=color)  # we already handled the x-label with ax1
            ax2.plot(df_filtered.index, df_filtered['Current (mA)'], color=color, alpha=0.8) # Added alpha for opacity
            ax2.tick_params(axis='y', labelcolor=color)

            fig_yy.tight_layout()  # otherwise the right y-label might be slightly clipped
            st.pyplot(fig_yy)

            # --- Battery Life Estimation using Average Current ---
            st.sidebar.header('Battery Life Estimation (using Avg Current)')
            if st.sidebar.button('Estimate Battery Life'):
                avg_current_ma = df_filtered['Current (mA)'].mean()
                if avg_current_ma > 0:
                    battery_capacity_ah = battery_capacity_mah / 1000
                    avg_current_a = avg_current_ma / 1000
                    estimated_life_hours = battery_capacity_ah / avg_current_a
                    estimated_life_days = estimated_life_hours / 24
                    st.sidebar.success(f"Estimated Battery Life for Selected Duration: {estimated_life_days:.2f} days")
                else:
                    st.sidebar.warning("Average current is zero or negative, cannot estimate battery life.")
        else:
            st.warning("No data available for the selected duration.")

    except FileNotFoundError:
        st.error(f"Error: The file '{selected_filename}' was not found.")
    except Exception as e:
        st.error(f"An error occurred: {e}")