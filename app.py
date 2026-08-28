import streamlit as st
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="Task Scheduler", layout="wide")
st.title("Daily Shift & Task Scheduler")

# --- 1. MOCK DATA (Will be replaced by your uploaded Excel/CSV) ---
@st.cache_data
def load_mock_data():
    # Added Days_Working to filter daily schedules
    workers_df = pd.DataFrame({
        "Worker_Name": ["Alice", "Bob", "Charlie", "Diana"],
        "Start_Time": ["07:00", "08:00", "07:00", "11:00"],
        "End_Time": ["15:30", "16:30", "15:30", "19:00"],
        "Days_Working": ["Mon, Tue, Wed, Thu, Fri", "Mon, Wed, Fri", "Tue, Thu, Sat, Sun", "Mon, Tue, Wed, Thu, Fri"]
    })
    
    tasks_df = pd.DataFrame({
        "Task_Name": ["Genomics Sequencing Setup", "Equipment QC", "Reagent Prep", "Review Logs"],
        "Duration_Hours": [2.0, 0.5, 1.0, 1.5],
        "Default_Quantity": [4, 2, 3, 1],
        "Priority": [True, True, False, False],
        "Assigned_To": [None, None, None, None] # Blank by default for manual override
    })
    return workers_df, tasks_df

workers_df, tasks_df = load_mock_data()
worker_names = workers_df["Worker_Name"].tolist()

# --- 2. TOP CONTROLS ---
# Day selector defaults to today's actual day of the week
days_of_week = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
current_day = datetime.now().strftime("%a") 
selected_day = st.selectbox("Select Day of the Week", days_of_week, index=days_of_week.index(current_day) if current_day in days_of_week else 0)

# Auto-determine who is working based on the selected day
workers_df["Working_Today?"] = workers_df["Days_Working"].apply(lambda x: selected_day in x)

st.markdown("---")

# --- 3. INTERACTIVE TABLES ---
col1, col2 = st.columns([1, 1.5]) # Make the tasks column a bit wider

with col1:
    st.subheader(f"1. Roster for {selected_day}")
    st.markdown("Uncheck call-outs or edit hours.")
    
    # st.data_editor makes the dataframe interactive
    edited_workers = st.data_editor(
        workers_df[["Working_Today?", "Worker_Name", "Start_Time", "End_Time"]],
        hide_index=True,
        key="worker_editor",
        use_container_width=True
    )

with col2:
    st.subheader("2. Today's Task Load")
    st.markdown("Adjust quantities, priorities, or manually assign tasks.")
    
    # Configure specific columns to be dropdowns or checkboxes
    edited_tasks = st.data_editor(
        tasks_df,
        column_config={
            "Assigned_To": st.column_config.SelectboxColumn(
                "Manual Override",
                help="Force assign to a specific person",
                options=worker_names
            ),
            "Priority": st.column_config.CheckboxColumn("Priority"),
            "Duration_Hours": st.column_config.NumberColumn("Hours/Task", min_value=0.1, step=0.1),
            "Default_Quantity": st.column_config.NumberColumn("Quantity Needed", min_value=0, step=1)
        },
        hide_index=True,
        key="task_editor",
        use_container_width=True
    )

st.markdown("---")

if st.button("Generate Today's Schedule", type="primary"):
    st.success("UI is wired up! Next step: plug these edited dataframes into the math solver.")
    # The optimization logic will go here
