# Home.py (New File for VOLT/RUNNER)
import streamlit as st

# Configure the page settings (browser tab title, icon, layout)
st.set_page_config(
    page_title="VOLT/RUNNER",
    page_icon="⚡",  # Optional: Adds an icon to the browser tab
)

# --- Page Title ---
st.title("⚡ VOLT/RUNNER 🏃")
st.markdown("---") # Adds a horizontal rule

# --- Introduction ---
st.header("Welcome!")
st.markdown(
    """
    This application provides tools for running electrical tests and analyzing the results.

    Navigate using the sidebar on the left to access the different modules:
    """
)

# --- Module Descriptions ---
col1, col2 = st.columns(2)

with col1:
    st.subheader("📊 Recorded Data")
    st.info(
        """
        **Purpose:** Visualize and analyze data from previously completed tests.
        - Load test results from CSV files.
        - Generate plots and summaries.
        - Compare results across different runs.
        """
    )
    # You could potentially add a button or link here if useful, though sidebar is primary
    # if st.button("Go to Recorded Data"):
    #    st.switch_page("pages/2_Recorded_Data.py") # Newer way to switch pages programmatically

with col2:
    st.subheader("⚙️ Measurement")
    st.success(
        """
        **Purpose:** Configure and initiate new measurement tests.
        - Set up test parameters.
        - Start the measurement process.
        - Monitor real-time values (if applicable).
        """
    )
    # if st.button("Go to Measurement"):
    #    st.switch_page("pages/1_Measurement.py")

st.markdown("---")

# --- Sidebar Guidance ---
st.sidebar.success("Select a module above to begin.")
st.sidebar.image("https://streamlit.io/images/brand/streamlit-logo-secondary-colormark-darktext.svg", use_column_width=True) # Example sidebar content

# --- Optional: Footer or Additional Info ---
st.markdown(
    """
    <hr>
    <div style='text-align: center;'>
        VOLT/RUNNER Application | © 2025
    </div>
    """, unsafe_allow_html=True
)

# Initialize any session state variables needed globally across pages
if 'test_config' not in st.session_state:
    st.session_state.test_config = {} # Example
if 'results_df' not in st.session_state:
    st.session_state.results_df = None # Example